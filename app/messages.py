"""Fixed server-spoken sentences, by language."""
from typing import Dict

MESSAGES: Dict[str, Dict[str, str]] = {
    "zh": {
        "task_ack": "好，我去弄，你继续说。",
        "confirm_end": "要结束吗？说结束就行。",
        "end_reply": "好，我来整理",
        "task_limit": "这次后台的事够多了，我先记下这个问题。",
        "nudge_point": "「{point}」还没展开，还在想吗？",
        "nudge_generic": "还在吗？卡住的话，先说一个最小的问题。",
        "found": "查到了：{conclusion}",
        "draft_done": "写好了，放在成果页里。",
        "draft_label": "已写好",
        "task_failed_label": "没弄成",
        "budget_label": "预算已耗尽，本次无法继续，请稍后再试。",
        "task_failed": "刚才那件事没弄成，我记在成果页了。",
        "budget": "预算已耗尽，本次无法继续，请稍后再试。",
        "fallback": "自动听写断了。现在按空格开始说话，说完再按一次。",
        "poster_failed": "画图失败，请再试一次。",
        "poster_budget": "预算已耗尽，本次无法继续，请稍后再试。",
        "default_title": "Blackout 成果",
        "reflect_both": "现在定了{decision}，还没定{open}。",
        "reflect_decision": "现在定了{decision}。",
        "reflect_open": "还没定{open}。",
        "key_rejected": "Meta 不接受现在的 key，AI 暂时帮不上忙。你说的话还在记录，说结束可以先看原话。",
        "credits_out": "你的 Meta 账户额度不够了，AI 暂时帮不上忙。你说的话还在记录。",
        "ai_unreachable": "我暂时连不上 AI。你说的话还在记录，可以继续说。",
        "ai_back": "连上了。",
        "asr_key_rejected": "Meta 不接受现在的 key，我听不到你。请按 Esc，然后换一个 key。",
    },
    "en": {
        "task_ack": "OK, I'm on it. Keep going.",
        "confirm_end": "Want to finish? Just say stop.",
        "end_reply": "OK, let me pull this together.",
        "task_limit": "That's a lot of background work for one session, so I'll note that as a question.",
        "nudge_point": "You haven't finished with {point}. Still thinking?",
        "nudge_generic": "Still there? If you're stuck, try saying the smallest question.",
        "found": "Found it: {conclusion}",
        "draft_done": "The draft is ready. It's on your result page.",
        "draft_label": "Draft ready",
        "task_failed_label": "Didn't work",
        "budget_label": "The budget is used up, so this couldn't finish.",
        "task_failed": "That didn't work. I noted it on your result page.",
        "budget": "The budget is used up, so I can't continue.",
        "fallback": "Automatic listening stopped. Press space to start talking, and press it again when you finish.",
        "poster_failed": "Couldn't draw the picture. Please try again.",
        "poster_budget": "The budget is used up, so the picture wasn't drawn.",
        "default_title": "Blackout result",
        "reflect_both": "So far: {decision}. Still open: {open}.",
        "reflect_decision": "So far: {decision}.",
        "reflect_open": "Still open: {open}.",
        "key_rejected": "Meta rejected the key, so the AI can't help right now. Your words are still being recorded. Say stop to see them.",
        "credits_out": "Your Meta account is out of credit, so the AI can't help right now. Your words are still being recorded.",
        "ai_unreachable": "I can't reach the AI right now. Your words are still being recorded, so keep going.",
        "ai_back": "I'm back.",
        "asr_key_rejected": "Meta rejected the key, so I can't hear you. Press Escape and change the key.",
    },
}


class _Keep(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def message(language: str, key: str, **values: str) -> str:
    """Return a fixed sentence in `language`, falling back to Chinese."""
    lang: str = language if language in MESSAGES else "zh"
    template: str = MESSAGES[lang].get(key, MESSAGES["zh"].get(key, key))
    if values:
        return template.format_map(_Keep(values))
    return template
