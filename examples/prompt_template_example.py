#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
展示PromptTemplate和ChatPromptTemplate的区别以及如何替换
"""

from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate

# 使用ChatPromptTemplate（项目中当前的用法）
# chat_prompt = ChatPromptTemplate.from_messages([
#     ("system", "你是一个AI助手，用简单语言回答问题。"),
#     ("human", "解释：{concept}")
# ])

chat_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("你是一个AI助手，用简单语言回答问题。"),
    HumanMessagePromptTemplate.from_template("解释：{concept}")
])


# 使用PromptTemplate（替代方案）
simple_prompt = PromptTemplate.from_template(
    "你是一个AI助手，用简单语言回答问题。\n用户: 解释：{concept}\n助手:"
)

# 示例输入
input_data = {"concept": "机器学习"}

print("=== ChatPromptTemplate 输出 ===")
chat_messages = chat_prompt.format_messages(**input_data)
for msg in chat_messages:
    print(f"{type(msg).__name__}: {msg.content}")

print("\n=== PromptTemplate 输出 ===")
simple_message = simple_prompt.format(**input_data)
print(f"String: {simple_message}")

# 展示在实际LLM调用中的区别
print("\n=== 模拟LLM调用 ===")
print("使用ChatPromptTemplate时，LLM接收的是消息列表:")
print(repr(chat_messages))

print("\n使用PromptTemplate时，LLM接收的是单个字符串:")
print(repr(simple_message))




# === ChatPromptTemplate 输出 ===
# SystemMessage: 你是一个AI助手，用简单语言回答问题。
# HumanMessage: 解释：机器学习
#
# === PromptTemplate 输出 ===
# String: 你是一个AI助手，用简单语言回答问题。
# 用户: 解释：机器学习
# 助手:
#
# === 模拟LLM调用 ===
# 使用ChatPromptTemplate时，LLM接收的是消息列表:
# [SystemMessage(content='你是一个AI助手，用简单语言回答问题。'), HumanMessage(content='解释：机器学习')]
#
# 使用PromptTemplate时，LLM接收的是单个字符串:
# '你是一个AI助手，用简单语言回答问题。\n用户: 解释：机器学习\n助手:'