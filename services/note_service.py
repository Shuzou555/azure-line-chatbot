"""Azure Table Storage にグループごとのノートを保存する。"""

import os
from datetime import datetime, timezone
from uuid import uuid4

from azure.data.tables import TableServiceClient


MAX_NOTE_LENGTH = 60_000


def _get_table_client():
    connection_string = os.getenv("AZURE_TABLES_CONNECTION_STRING")
    if not connection_string:
        raise RuntimeError("環境変数 AZURE_TABLES_CONNECTION_STRING が設定されていません。")

    table_name = os.getenv("NOTES_TABLE_NAME", "GroupNotes")
    # 接続文字列を使って対象ストレージアカウントへ接続し、ノート保存用テーブルを取得する。
    service_client = TableServiceClient.from_connection_string(connection_string)
    # テーブルがまだない初回だけ作成する。既に存在する場合は何もしない。
    service_client.create_table_if_not_exists(table_name)
    return service_client.get_table_client(table_name)


def save_note(conversation_id: str, content: str, document_type: str) -> None:
    """ノートまたは議事録を会話（グループまたは個人）単位で保存する。"""
    if not conversation_id:
        raise ValueError("保存先の会話IDがありません。")
    if len(content) > MAX_NOTE_LENGTH:
        raise ValueError("ノートは60,000文字以内で登録してください。")

    # 会話IDをPartitionKeyにして、ノート／議事録をAzure Table Storageへ1件追加する。
    # 同じ会話IDのデータが同一パーティションにまとまり、会話ごとに検索できる。
    _get_table_client().create_entity(
        {
            "PartitionKey": conversation_id,
            "RowKey": str(uuid4()),
            "Content": content,
            "DocumentType": document_type,
            "CreatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


def list_notes(conversation_id: str, limit: int = 5) -> list[dict[str, str]]:
    """新しい順に、指定数までノート・議事録を返す。"""
    if not conversation_id:
        return []

    # ODataクエリで、指定した会話ID（グループ・個人トーク）と一致するノートだけを取得する。
    # パラメーターを使うため、会話IDを文字列として安全に条件へ渡せる。
    entities = _get_table_client().query_entities(
        query_filter="PartitionKey eq @conversation_id",
        parameters={"conversation_id": conversation_id},
    )
    latest = sorted(
        entities,
        key=lambda entity: entity.get("CreatedAt", ""),
        reverse=True,
    )[:limit]
    return [
        {
            "content": entity["Content"],
            "document_type": entity.get("DocumentType", "ノート"),
        }
        for entity in latest
    ]
