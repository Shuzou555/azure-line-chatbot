"""Microsoft Foundry のモデルデプロイを使ったチャット応答の生成。"""

import os
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI


SYSTEM_PROMPT = (
    "あなたはShuzoのAI版個人利用の公式LINEチャットボットです。"
    "簡潔で丁寧な日本語で回答してください。"
    "松岡修造のように熱血な男を演じて下さい"
    "ユーザーが会社や事業を経営していると推測してはいけません。"
    "存在が確認できない商品、サービス、会社、実績を作ってはいけません。"
    "ユーザーが提供していない個人情報や事実を推測してはいけません。"
    "情報が不足している場合は、推測せず「情報がありません」と回答してください。"
    "架空の商品名、価格、売上、顧客、サービスを事実として紹介してはいけません。"
)

JAPANESE_WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"環境変数 {name} が設定されていません。")
    return value


def ask_ai(
    message: str,
    history: Sequence[dict[str, str]] | None = None,
    notes_context: str | None = None,
) -> str:
    """Foundry の Responses API で、会話履歴と保存ノートを参照して応答する。"""
    if not message or not message.strip():
        return "メッセージを入力してください。"

    client = OpenAI(
        # Microsoft Foundry の Responses API エンドポイントへ接続するクライアントを作成する。
        base_url=_required_env("AZURE_FOUNDRY_ENDPOINT"),
        api_key=_required_env("AZURE_FOUNDRY_API_KEY"),
    )

    current_time = datetime.now(ZoneInfo("Asia/Tokyo"))
    current_datetime_text = current_time.strftime("%Y年%m月%d日 %H:%M")
    current_weekday = JAPANESE_WEEKDAYS[current_time.weekday()]

    input_messages = [
        {"role": "developer", "content": SYSTEM_PROMPT},
        {
            "role": "developer",
            "content": (
                f"現在日時は {current_datetime_text}（{current_weekday}曜日、日本時間）です。"
                "日付・曜日・時刻・今日・明日・昨日に関する質問は、"
                "この現在日時を正しい基準として回答してください。"
                "学習時点の日時を現在日時として扱ったり、日付を推測したりしないでください。"
            ),
        },
    ]
    if notes_context:
        input_messages.append(
            {
                "role": "developer",
                "content": (
                    "以下は、この会話だけに登録されたノート・議事録です。"
                    "質問への回答に関係する場合のみ参照してください。"
                    "記載がない事実は推測せず、情報がないと伝えてください。\n\n"
                    f"{notes_context}"
                ),
            }
        )

    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            input_messages.append({"role": role, "content": content})

    input_messages.append(
        {"role": "user", "content": message.strip()}
    )

    # モデルへシステム指示・現在日時・ノート・会話履歴・今回の質問を送るAI問い合わせ。
    # model にはFoundry上で作成した「デプロイ名」を指定する。
    response = client.responses.create(
        model=_required_env("AZURE_FOUNDRY_MODEL"),
        input=input_messages,
        temperature=0.3,
        max_output_tokens=800,
    )

    return response.output_text.strip() or "回答を生成できませんでした。"
