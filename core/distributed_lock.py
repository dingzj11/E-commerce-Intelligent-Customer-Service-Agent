"""分布式锁模块

基于 Redis 实现可靠的分布式锁，包括：
- 单实例锁：SET NX + EX + Lua 释放 + 看门狗续期
- Redlock 多实例锁：N 个独立 Redis 实例的多数派协议

特性：
- SET NX + EX 原子操作，防止死锁
- 锁持有者标识（instance_id + 线程ID），防止误释放
- Lua 脚本原子释放
- 自动重试 + 指数退避
- 支持上下文管理器（with 语句）
- 锁续期（看门狗）防止超时未完成
- Redlock 算法：跨多个独立 Redis 实例的分布式锁（更安全）

【面试核心——Redlock 算法原理（Redis 作者 antirez 提出）】
1. 客户端获取当前时间戳（微秒级）
2. 依次向 N 个 Redis 实例请求锁（SET NX PX），设置超时时间远小于锁 TTL
3. 统计获取锁成功的实例数，计算获取锁花费的总时间
4. 如果成功数 >= N/2+1（多数派），且总耗时 < 锁 TTL，则获取成功
5. 锁的有效期 = 原始 TTL - 获取耗时
6. 如果获取失败，向所有实例发送释放请求

为什么 Redlock 比单实例更安全：
- 单实例：Redis 宕机 → 锁丢失 → 并发安全问题
- Redlock：需要多数 Redis 同时宕机才会丢失锁
- 适用于对一致性要求极高的场景（资金交易等）
"""

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Optional

from redis.exceptions import RedisError

from core.config import get_config
from core.redis_client import get_redis_client, is_redis_available

logger = logging.getLogger("distributed_lock")

# 释放锁的 Lua 脚本（原子操作：只释放自己持有的锁）
_RELEASE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# 锁续期 Lua 脚本
_RENEW_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class DistributedLock:
    """基于 Redis 的分布式锁

    使用示例:
        lock = DistributedLock("order:ORD123")
        with lock.acquire():
            # 临界区代码
            do_something()

        # 或作为装饰器
        lock = DistributedLock("order:ORD123")
        @lock.guard
        def critical_operation():
            pass
    """

    def __init__(
        self,
        resource_key: str,
        ttl: int = 10,
        retry_times: int = 3,
        retry_delay: float = 0.2,
        auto_renew: bool = True,
    ):
        """
        Args:
            resource_key: 资源标识（如 "order:ORD123"）
            ttl: 锁超时时间（秒），防止死锁
            retry_times: 获取锁失败时的重试次数
            retry_delay: 重试间隔（秒）
            auto_renew: 是否启动看门狗自动续期
        """
        cfg = get_config()
        self._key = f"lock:{resource_key}"
        self._ttl = ttl or cfg.lock_timeout
        self._retry_times = retry_times or cfg.max_retry_on_lock
        self._retry_delay = retry_delay
        self._auto_renew = auto_renew

        # 锁持有者唯一标识
        self._owner = f"{cfg.instance_id or socket.gethostname()}:{threading.get_ident()}:{uuid.uuid4().hex[:8]}"

        self._renew_thread: Optional[threading.Thread] = None
        self._renew_stop: threading.Event = threading.Event()

    @property
    def lock_key(self) -> str:
        return self._key

    @property
    def owner(self) -> str:
        return self._owner

    def acquire(self, blocking: bool = True) -> bool:
        """获取锁

        Returns:
            True 获取成功，False 获取失败（仅在 blocking=False 时）
        """
        client = get_redis_client()

        for attempt in range(self._retry_times + 1):
            try:
                # SET key value NX EX ttl —— 原子操作
                acquired = client.set(
                    self._key, self._owner, nx=True, ex=self._ttl
                )
                if acquired:
                    logger.debug("获取锁成功: %s (attempt %s)", self._key, attempt + 1)

                    if self._auto_renew:
                        self._start_renew()
                    return True

                if not blocking:
                    return False

                if attempt < self._retry_times:
                    delay = self._retry_delay * (2 ** attempt)  # 指数退避
                    logger.debug("锁被占用，%s秒后重试: %s", delay, self._key)
                    time.sleep(delay)

            except RedisError as e:
                logger.warning("Redis 异常，获取锁失败: %s", e)
                if attempt < self._retry_times:
                    time.sleep(self._retry_delay)
                else:
                    raise

        logger.warning("获取锁失败（已达最大重试次数）: %s", self._key)
        return False

    def release(self) -> bool:
        """释放锁（原子操作，只释放自己持有的）"""
        self._stop_renew()

        try:
            client = get_redis_client()
            # 使用 Lua 脚本保证原子性
            release_lock = client.register_script(_RELEASE_LUA)
            result = release_lock(keys=[self._key], args=[self._owner])
            if result:
                logger.debug("释放锁成功: %s", self._key)
                return True
            else:
                logger.debug("锁已过期或被其他持有者释放: %s", self._key)
                return False
        except RedisError as e:
            logger.warning("释放锁时 Redis 异常: %s", e)
            return False
        except Exception:  # 连接已断开
            return False

    def extend(self, additional_ttl: Optional[int] = None) -> bool:
        """延长锁的过期时间"""
        ttl = additional_ttl or self._ttl
        try:
            client = get_redis_client()
            renew_lock = client.register_script(_RENEW_LUA)
            result = renew_lock(keys=[self._key], args=[self._owner, ttl])
            return bool(result)
        except RedisError:
            return False

    def is_locked(self) -> bool:
        """检查锁是否仍被自己持有"""
        try:
            current_owner = get_redis_client().get(self._key)
            return current_owner is not None and current_owner.decode() == self._owner
        except RedisError:
            return False

    def _start_renew(self):
        """启动锁续期线程（看门狗）"""
        self._renew_stop.clear()
        self._renew_thread = threading.Thread(
            target=self._renew_loop,
            daemon=True,
            name=f"lock-renew-{self._key}",
        )
        self._renew_thread.start()

    def _stop_renew(self):
        """停止锁续期线程"""
        self._renew_stop.set()
        if self._renew_thread and self._renew_thread.is_alive():
            self._renew_thread.join(timeout=2)

    def _renew_loop(self):
        """锁续期循环：每隔 ttl/3 秒续期一次"""
        interval = max(self._ttl // 3, 1)
        while not self._renew_stop.wait(interval):
            try:
                if not self.extend():
                    logger.warning("锁续期失败，锁可能已过期: %s", self._key)
                    break
                logger.debug("锁续期成功: %s", self._key)
            except Exception as e:
                logger.error("锁续期异常: %s", e)

    @contextmanager
    def guard(self, blocking: bool = True):
        """上下文管理器，自动获取和释放锁

        with lock.guard():
            # 临界区代码
            pass
        """
        acquired = self.acquire(blocking=blocking)
        if not acquired:
            raise LockAcquisitionError(
                f"无法获取分布式锁: {self._key}，资源正在被其他实例使用"
            )
        try:
            yield
        finally:
            self.release()

    def __call__(self, func: Callable) -> Callable:
        """作为装饰器使用"""
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            with self.guard():
                return func(*args, **kwargs)

        return wrapper

    def __enter__(self):
        if not self.acquire():
            raise LockAcquisitionError(f"无法获取分布式锁: {self._key}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


class LockAcquisitionError(Exception):
    """分布式锁获取失败异常"""
    pass


# ==================== 便捷函数 ====================


import socket


def distributed_lock(
    resource_key: str,
    ttl: int = 10,
    auto_renew: bool = True,
):
    """创建分布式锁的便捷工厂函数

    用法:
        lock = distributed_lock("order:ORD123")

        with lock.guard():
            do_critical_work()
    """
    return DistributedLock(
        resource_key=resource_key,
        ttl=ttl,
        auto_renew=auto_renew,
    )


def with_distributed_lock(
    resource_pattern: str,
    ttl: int = 10,
):
    """分布式锁装饰器，根据函数参数动态构建锁键

    用法:
        @with_distributed_lock("cancel_order:{order_id}")
        def cancel_order(order_id: str):
            pass
    """
    import inspect

    def decorator(func: Callable) -> Callable:
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            call_args = inspect.getcallargs(func, *args, **kwargs)
            key = resource_pattern.format(**call_args)
            lock = DistributedLock(key, ttl=ttl)
            with lock.guard():
                return func(*args, **kwargs)

        return wrapper

    return decorator


# ==================== Redlock 多实例分布式锁 ====================


class Redlock:
    """Redlock 算法——跨多个独立 Redis 实例的分布式锁

    面试重点——与单实例锁的关键区别：
    1. 需要在多数(N/2+1)个实例上成功获取锁才认为获取成功
    2. 锁的有效期 = TTL - 获取锁耗时（防止网络延迟导致锁过期）
    3. 释放时向所有实例发送释放请求
    4. 容忍少数 Redis 实例故障

    参数推荐：
    - N=5 (通常奇数个节点以便多数投票)
    - TTL = 业务执行时间的 2-3 倍
    - 获取单个实例的超时 = TTL / N（毫秒级）

    争议与讨论（面试加分项）：
    Martin Kleppmann 曾对 Redlock 提出质疑，认为它不安全。
    核心争论点：GC pause 或网络延迟可能导致锁在不知情的情况下过期。
    应对方案：引入 fencing token（单调递增 token），资源层校验 token。
    """

    def __init__(
        self,
        redis_hosts: list,
        ttl: int = 10,
        retry_times: int = 3,
        retry_delay: float = 0.2,
    ):
        """
        Args:
            redis_hosts: Redis 实例列表 [{"host": "...", "port": ..., "password": ...}, ...]
            ttl: 锁超时时间（秒）
            retry_times: 重试次数
            retry_delay: 初始重试延迟
        """
        import socket

        self._hosts = redis_hosts
        self._ttl = ttl
        self._retry_times = retry_times
        self._retry_delay = retry_delay
        self._quorum = len(redis_hosts) // 2 + 1  # 多数派

        cfg = get_config()
        self._owner = (
            f"{cfg.instance_id or socket.gethostname()}:"
            f"{threading.get_ident()}:{uuid.uuid4().hex[:8]}"
        )

        # 为每个 Redis 实例创建连接
        self._clients = []
        for host_info in redis_hosts:
            try:
                client = redis.Redis(
                    host=host_info["host"],
                    port=host_info.get("port", 6379),
                    password=host_info.get("password", ""),
                    socket_timeout=min(float(ttl) / len(redis_hosts) * 1000 * 0.5, 200),
                    socket_connect_timeout=min(float(ttl) / len(redis_hosts) * 1000 * 0.5, 200),
                    decode_responses=False,
                )
                self._clients.append(client)
            except Exception as e:
                logger.warning("Redlock: Redis 实例连接失败 %s:%s, err=%s",
                             host_info["host"], host_info.get("port", 6379), e)

        if len(self._clients) < self._quorum:
            raise RuntimeError(
                f"Redlock: 可用 Redis 实例数({len(self._clients)}) "
                f"不足多数派({self._quorum})"
            )

    def acquire(self, resource_key: str, blocking: bool = True) -> Optional[str]:
        """获取 Redlock 锁

        Returns:
            锁的 value（用于释放），None 表示获取失败
        """
        lock_key = f"redlock:{resource_key}"
        ttl_ms = int(self._ttl * 1000)

        for attempt in range(self._retry_times + 1):
            start_time = time.time()

            # 阶段 1：尝试在所有实例上获取锁
            acquired_count = 0
            for client in self._clients:
                try:
                    ok = client.set(
                        lock_key, self._owner, nx=True, px=ttl_ms,
                    )
                    if ok:
                        acquired_count += 1
                except RedisError:
                    continue

            elapsed_ms = (time.time() - start_time) * 1000

            # 阶段 2：判断是否获得多数派支持
            if acquired_count >= self._quorum and elapsed_ms < ttl_ms:
                logger.debug(
                    "Redlock 获取成功: key=%s, acquired=%s/%s, elapsed=%.1fms",
                    lock_key, acquired_count, len(self._clients), elapsed_ms,
                )
                return self._owner

            # 阶段 3：获取失败，释放已在部分实例上获取的锁
            self._release_all(lock_key)

            if not blocking:
                return None

            if attempt < self._retry_times:
                delay = self._retry_delay * (2 ** attempt) + random.random() * 0.1
                logger.debug("Redlock 重试 %s/%s: %s", attempt + 1, self._retry_times, lock_key)
                time.sleep(delay)

        logger.warning("Redlock 获取失败(重试耗尽): %s", lock_key)
        return None

    def release(self, resource_key: str, lock_value: str) -> bool:
        """释放 Redlock 锁"""
        lock_key = f"redlock:{resource_key}"
        return self._release_all(lock_key)

    def _release_all(self, lock_key: str) -> bool:
        """向所有实例发送释放请求"""
        released_count = 0
        for client in self._clients:
            try:
                release_lock = client.register_script(_RELEASE_LUA)
                if release_lock(keys=[lock_key], args=[self._owner]):
                    released_count += 1
            except RedisError:
                continue
        return released_count > 0

    @contextmanager
    def guard(self, resource_key: str):
        """Redlock 上下文管理器"""
        lock_value = self.acquire(resource_key)
        if lock_value is None:
            raise LockAcquisitionError(f"Redlock 获取失败: {resource_key}")
        try:
            yield
        finally:
            self.release(resource_key, lock_value)


import random
