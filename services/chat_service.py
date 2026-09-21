"""LINEから受け取ったメッセージの振り分け。"""

from services.conversation_service import load_history, save_history
from services.fabric_service import get_sales
from services.note_service import list_notes, save_note
from services.openai_service import ask_ai
from services.search_service import search_document


DOCUMENT_REGISTER_COMMANDS = {
    "#ノート登録": "ノート",
    "#議事録": "議事録",
}
NOTE_INTRODUCTION_COMMAND = "ノートを紹介して"
MAX_REFERENCE_CHARS = 12_000


def _build_notes_context(notes: list[dict[str, str]]) -> str | None:
    """同じ会話に保存されたノートをAI参照用テキストへ整形する。"""
    if not notes:
        return None

    sections: list[str] = []
    total_length = 0
    for note in notes:
        section = f"【{note['document_type']}】\n{note['content']}"
        if total_length + len(section) > MAX_REFERENCE_CHARS:
            remaining = MAX_REFERENCE_CHARS - total_length
            if remaining > 0:
                sections.append(section[:remaining] + "…")
            break
        sections.append(section)
        total_length += len(section)

    return "\n\n".join(sections)


class ChatService:
    def chat(self, message: str, conversation_id: str) -> str:
        """会話単位でメッセージを処理して応答を返す。"""
        message = message.strip()
        if not message:
            return "メッセージを入力してください。"

        command, document_type = next(
            (
                (command, document_type)
                for command, document_type in DOCUMENT_REGISTER_COMMANDS.items()
                if message.startswith(command)
            ),
            (None, None),
        )
        if command:
            note = message.removeprefix(command).strip()
            if not note:
                return f"登録する{document_type}を、{command} の次の行に入力してください。"
            # #ノート登録／#議事録の本文を、その会話専用のAzure Table Storageへ保存する。
            save_note(conversation_id, note, document_type)
            return f"{document_type}を登録しました。"

        if message == NOTE_INTRODUCTION_COMMAND:
            # この会話IDに紐づく保存済みノートだけを検索し、LINE上で一覧表示する。
            notes = list_notes(conversation_id)
            if not notes:
                return "このトークには登録済みのノートがありません。"
            formatted_notes = "\n\n".join(
                f"{index}. 【{note['document_type']}】\n{note['content']}"
                for index, note in enumerate(notes, start=1)
            )
            return f"登録済みのノート・議事録です。\n\n{formatted_notes}"

        if "売上" in message:
            # 将来の売上データ連携用の問い合わせ窓口（現時点ではダミー応答）を呼び出す。
            return get_sales()

        if "マニュアル" in message:
            # 将来の社内マニュアル検索用の問い合わせ窓口（現時点ではダミー応答）を呼び出す。
            return search_document(message)

        # 同一トークの直近会話を取得し、文脈を保った回答を作るために使う。
        history = load_history(conversation_id)
        # 同一トークのノートを検索し、回答の参考情報としてAIへ渡す。
        notes_context = _build_notes_context(list_notes(conversation_id))
        # Foundry のモデルへ質問・履歴・ノートを送信して、回答を生成する。
        answer = ask_ai(message, history, notes_context)
        # 次回以降の会話で文脈を引き継げるよう、質問と回答を履歴に記録する。
        save_history(conversation_id, message, answer)
        return answer
