"""会話履歴の管理。

現時点では Azure Functions のプロセス内メモリに保存する。
プロセスの再起動・スケールアウト時には履歴が失われるため、本番では
Azure Table Storage や Cosmos DB などの永続ストアに置き換えること。
"""

import os
from collections import defaultdict
from threading import Lock


_history_by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
_history_lock = Lock()
_max_messages = int(os.getenv("CONVERSATION_HISTORY_MAX_MESSAGES", "20"))


def load_history(user_id: str) -> list[dict[str, str]]:
    """ユーザーの履歴をコピーして返す。"""
    if not user_id:
        return []

    with _history_lock:
        # 会話履歴を読み出す。現状は外部DBではなく、Functionsプロセス内メモリへの問い合わせ。
        return list(_history_by_user[user_id])


def save_history(user_id: str, question: str, answer: str) -> None:
    """ユーザー発話とボット応答を、指定上限まで保存する。"""
    if not user_id:
        return

    entries = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    with _history_lock:
        # 次のAI問い合わせで会話文脈に利用するため、ユーザー発話と回答をペアで記録する。
        history = _history_by_user[user_id]
        history.extend(entries)
        if _max_messages > 0:
            del history[:-_max_messages]
