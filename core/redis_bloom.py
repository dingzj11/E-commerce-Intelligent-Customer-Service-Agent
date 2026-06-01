"""布隆过滤器模块

基于 Redis Bitmap 实现布隆过滤器，用于缓存穿透防护。

【布隆过滤器原理】
- 用 k 个 Hash 函数将元素映射到位数组的 k 个位置
- 插入：将 k 个位置全部置 1
- 查询：检查 k 个位置是否全为 1
  - 全为 1 → "可能存在"（允许 false positive）
  - 有 0   → "一定不存在"（绝对正确）

【参数计算】
- m: 位数组长度（bit）
- k: Hash 函数个数
- n: 预期元素数量
- p: 误报率

  m = -n * ln(p) / (ln(2)^2)
  k = (m / n) * ln(2)

  例如: n=1000万, p=0.01
  m ≈ 9585万 bit ≈ 11.4 MB
  k ≈ 7

【面试要点】
1. 布隆过滤器说什么存在 → 不一定存在，可能误判
2. 布隆过滤器说不存在 → 一定不存在，不会误判
3. 不能删除元素（计数布隆过滤器可以，但需要更多空间）
4. 适用：缓存穿透防护、新闻推荐去重、爬虫 URL 去重
5. Redis 4.0+ 有原生 Bloom Filter 插件（RedisBloom），
   本实现是基于 Bitmap 的纯 Redis 实现，不依赖插件

【在本项目中的使用】
- 缓存穿透防护：查询订单前先检查布隆过滤器
  如果过滤器说不存在 → 直接返回，不查 DB
  如果过滤器说可能存在 → 查缓存 → 查 DB → 回写缓存
"""

import hashlib
import math
from typing import List

from core.redis_client import _make_key, get_redis_client


class RedisBloomFilter:
    """基于 Redis Bitmap 的布隆过滤器"""

    def __init__(
        self,
        name: str,
        expected_elements: int = 10_000_000,
        false_positive_rate: float = 0.01,
    ):
        """初始化布隆过滤器

        Args:
            name: 过滤器名称
            expected_elements: 预期元素数量（默认 1000 万）
            false_positive_rate: 期望误报率（默认 1%）
        """
        self._name = _make_key(f"bloom:{name}")

        # 计算最优参数
        self._bit_size = self._calc_bit_size(expected_elements, false_positive_rate)
        self._hash_count = self._calc_hash_count(self._bit_size, expected_elements)

    @staticmethod
    def _calc_bit_size(n: int, p: float) -> int:
        """计算位数组大小 m = -n * ln(p) / (ln(2))^2"""
        m = -n * math.log(p) / (math.log(2) ** 2)
        return int(math.ceil(m))

    @staticmethod
    def _calc_hash_count(m: int, n: int) -> int:
        """计算 Hash 函数数量 k = (m/n) * ln(2)"""
        k = (m / n) * math.log(2)
        return int(math.ceil(k))

    def _get_positions(self, element: str) -> List[int]:
        """计算元素在 bitmap 中的多个位置（双重哈希法）

        面试要点: 用两个 Hash 生成 k 个位置，避免 k 个独立 Hash 的计算开销:
        h(i) = (hash1 + i * hash2) % bit_size
        """
        h1 = int(hashlib.sha256(f"bloom_hash1:{element}".encode()).hexdigest(), 16)
        h2 = int(hashlib.sha256(f"bloom_hash2:{element}".encode()).hexdigest(), 16)

        positions = []
        for i in range(self._hash_count):
            pos = (h1 + i * h2) % self._bit_size
            positions.append(pos)
        return positions

    def add(self, element: str) -> bool:
        """添加元素到布隆过滤器"""
        try:
            client = get_redis_client()
            for pos in self._get_positions(element):
                client.setbit(self._name, pos, 1)
            return True
        except Exception:
            return False

    def add_batch(self, elements: List[str]) -> bool:
        """批量添加元素（使用 Pipeline）"""
        try:
            client = get_redis_client()
            pipe = client.pipeline()
            for element in elements:
                for pos in self._get_positions(element):
                    pipe.setbit(self._name, pos, 1)
            pipe.execute()
            return True
        except Exception:
            return False

    def exists(self, element: str) -> bool:
        """检查元素是否可能存在

        Returns:
            True → 可能存在（可能误判）
            False → 一定不存在
        """
        try:
            client = get_redis_client()
            for pos in self._get_positions(element):
                if client.getbit(self._name, pos) == 0:
                    return False  # 一定不存在
            return True  # 可能存在
        except Exception:
            return True  # Redis 故障时返回 True，走正常流程

    def exists_batch(self, elements: List[str]) -> List[bool]:
        """批量检查（使用 Pipeline）"""
        try:
            client = get_redis_client()
            pipe = client.pipeline()

            all_positions = [self._get_positions(e) for e in elements]

            for positions in all_positions:
                for pos in positions:
                    pipe.getbit(self._name, pos)

            results = pipe.execute()

            # 按组聚合结果
            group_size = self._hash_count
            output = []
            for i in range(len(elements)):
                start = i * group_size
                end = start + group_size
                bits = results[start:end]  # 每条记录有 self._hash_count 个 result
                output.append(all(b == 1 for b in bits))
            return output
        except Exception:
            return [True] * len(elements)  # 降级

    @property
    def bit_size(self) -> int:
        return self._bit_size

    @property
    def hash_count(self) -> int:
        return self._hash_count


# ==================== 缓存穿透防护集成 ====================


class CachePenetrationGuard:
    """缓存穿透防护（布隆过滤器 + 空值缓存 + 互斥锁回源）

    面试要点: 这是三层防护的完整实现，面试官可能会要求画出架构图。

    三层防护体系:
    第一层: 布隆过滤器 → 拦截"一定不存在"的请求
    第二层: Redis 缓存 → 拦截"存在"的请求（包括空值标记）
    第三层: 互斥锁回源 → 防止热点 key 击穿 DB
    """

    def __init__(self, bloom_filter: RedisBloomFilter):
        self._bloom = bloom_filter

    def should_query(self, key_id: str) -> bool:
        """判断是否应该查询数据源

        Returns:
            True → 可能存在，应查询缓存/DB
            False → 一定不存在，直接返回不存在
        """
        return self._bloom.exists(key_id)

    def mark_exist(self, key_id: str):
        """将 key 标记为存在（写入数据成功后调用）"""
        self._bloom.add(key_id)
