import hashlib
import hmac
import json
import logging
import os

import azure.functions as func
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)

from services.chat_service import ChatService


app = func.FunctionApp()
chat_service = ChatService()

# Azure Functions のアプリ設定から、LINE Messaging APIを呼ぶための認証情報を取得する。
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if not CHANNEL_ACCESS_TOKEN:
    raise ValueError("LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
if not CHANNEL_SECRET:
    raise ValueError("LINE_CHANNEL_SECRET が設定されていません")

# LINE返信APIの各リクエストで利用するアクセストークン設定を作成する。
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)


def _is_valid_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    # LINE が送信した本文から署名を再計算し、Webhook がLINE由来で改ざんされていないか確認する。
    digest = hmac.new(
        CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected_signature = __import__("base64").b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def _conversation_id(source: dict) -> str | None:
    """グループ・複数人トークは共有ID、個人トークはユーザーIDを使う。"""
    return source.get("groupId") or source.get("roomId") or source.get("userId")


def _bot_mention_ranges(message: dict) -> list[tuple[int, int]]:
    """Bot自身へのメンション位置（文字列インデックス）を返す。"""
    return [
        (mention["index"], mention["index"] + mention["length"])
        for mention in message.get("mention", {}).get("mentionees", [])
        if mention.get("isSelf") is True
        and isinstance(mention.get("index"), int)
        and isinstance(mention.get("length"), int)
    ]


def _remove_bot_mentions(text: str, mention_ranges: list[tuple[int, int]]) -> str:
    """Botへのメンション表記を質問本文から取り除く。"""
    for start, end in sorted(mention_ranges, reverse=True):
        text = text[:start] + text[end:]
    return text.strip()


# LINEからWebhookを受信するHTTPエンドポイント。LINE側には /api/lineWebhook を登録する。
# LINE独自の署名検証を行うため、Functionsのキー認証は使用しない。
@app.route(route="lineWebhook", auth_level=func.AuthLevel.ANONYMOUS)
def line_webhook(req: func.HttpRequest) -> func.HttpResponse:
    # LINEがPOSTしたWebhook本文と、本文の正当性を確認するための署名ヘッダーを取得する。
    body = req.get_body()
    signature = req.headers.get("x-line-signature")

    # 署名が一致しないリクエストはLINE由来でない可能性があるため、AI処理をせず401で拒否する。
    if not _is_valid_signature(body, signature):
        logging.warning("LINE webhook signature validation failed")
        return func.HttpResponse("Invalid signature", status_code=401)

    try:
        # LINE Webhook のJSONから、受信したメッセージイベント一覧を取得する。
        events = json.loads(body.decode("utf-8")).get("events", [])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return func.HttpResponse("Invalid JSON", status_code=400)

    if not events:
        return func.HttpResponse("OK")

    for event in events:
        # イベント内のメッセージ情報を取り出し、テキスト以外（画像・スタンプ等）は対象外にする。
        message = event.get("message", {})
        if event.get("type") != "message" or message.get("type") != "text":
            continue

        # 送信元の種別とIDから、会話の区切り（個人・グループ・複数人トーク）を判定する。
        source = event.get("source", {})
        mention_ranges = _bot_mention_ranges(message)
        is_group_chat = source.get("type") in {"group", "room"}
        if is_group_chat and not mention_ranges:
            logging.info("Skipped group message without bot mention")
            continue

        # 会話IDは履歴・ノートをトークごとに分離して保存・検索するために使用する。
        conversation_id = _conversation_id(source)
        # replyToken は今回受信したイベントへ返信するための、一回限りのLINEトークン。
        reply_token = event.get("replyToken")
        user_message = _remove_bot_mentions(
            message.get("text", ""), mention_ranges
        )
        if not conversation_id or not reply_token:
            logging.warning("Skipped LINE event without conversation ID or reply token")
            continue
        if not user_message:
            answer = "ご用件を入力してください。"
        else:
            try:
                # メッセージ・会話履歴・登録ノートを渡して、AIへの回答生成リクエストを実行する。
                answer = chat_service.chat(user_message, conversation_id)
            except Exception:
                logging.exception("Chat Error")
                answer = "現在AIへ接続できません。"

        # LINE Messaging APIクライアントを作成し、今回のイベントへの返信リクエストを送る。
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                logging.info("LINE reply started: reply_length=%d", len(answer))
                # 受信イベントの replyToken を使い、生成した回答を同じLINEトークへ返信するAPIリクエスト。
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=answer)],
                    )
                )
                logging.info("LINE reply succeeded")
            except Exception:
                logging.exception("LINE reply failed")
                return func.HttpResponse("LINE reply failed", status_code=500)

    return func.HttpResponse("OK")
