# -*- coding: utf-8 -*-
"""
角色卡模块：加载 config/role_cards.json，并按角色卡做执行对象匹配。

设计原则（硬性规则，不是建议）：
- 一个工作项能分给谁，只看角色卡的「能力标签」是否含有所需能力、
  且「负责任务类型」是否包含该任务类型，两条同时满足才算匹配。
- 改派复核走同一套规则，保证对话里临时改派也不能绕过角色卡。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROLE_CARDS_PATH = os.path.join(BASE_DIR, "config", "role_cards.json")


def load_role_cards(path=DEFAULT_ROLE_CARDS_PATH):
    """读取角色卡列表，返回 [card, ...]。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["角色卡"]


def card_matches(card, capability, task_type):
    """判断一张角色卡是否能承接 (能力, 任务类型)。"""
    return capability in card.get("能力标签", []) and task_type in card.get("负责任务类型", [])


def find_candidates(cards, capability, task_type):
    """返回所有能承接该工作项的角色卡。"""
    return [c for c in cards if card_matches(c, capability, task_type)]


def find_holder(cards, holder_name):
    """按承担者名字反查 (角色卡, 承担者)，找不到返回 (None, None)。"""
    for card in cards:
        if holder_name in card.get("承担者", []):
            return card, holder_name
    return None, None


def check_assignment(cards, capability, task_type, holder_name):
    """
    复核一次具体分配是否合法（供改派使用）。
    返回 (是否合法, 原因说明)。
    """
    card, holder = find_holder(cards, holder_name)
    if holder is None:
        # 也允许直接按角色名改派（如“改派给测试Agent”），取该角色当前第一位承担者
        for c in cards:
            if c["角色名"] == holder_name and c.get("承担者"):
                card, holder = c, c["承担者"][0]
                break
    if holder is None:
        return False, "执行对象「%s」不在任何角色卡的承担者名单中" % holder_name
    if not card_matches(card, capability, task_type):
        return False, (
            "角色卡复核不通过：%s（%s）的能力标签 %s 不含「%s」，"
            "或不负责「%s」类任务" % (
                holder, card["角色名"], card.get("能力标签", []), capability, task_type)
        )
    return True, "由 %s（%s）承接" % (holder, card["角色名"])


def assign(cards, capability, task_type, load_hours):
    """
    为一个工作项挑执行对象：在所有匹配的角色卡的承担者中，
    选当前累计工时（load_hours: {承担者: 小时}）最小的一位，实现简单负载均衡。
    返回 dict {角色, 承担者, 角色类型}；无人可派时返回 None（由调用方报错）。
    """
    candidates = find_candidates(cards, capability, task_type)
    best = None
    for card in candidates:
        for holder in card.get("承担者", []):
            hours = load_hours.get(holder, 0)
            if best is None or hours < best[0]:
                best = (hours, card, holder)
    if best is None:
        return None
    _, card, holder = best
    return {"角色": card["角色名"], "承担者": holder, "角色类型": card["角色类型"]}
