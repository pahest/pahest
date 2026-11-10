"""Small but realistic API answers for claude.ai and chatgpt.com."""

ROOT = "00000000-0000-4000-8000-000000000000"


def claude_conv(cid="c1", name="Plan a trip", updated="2026-11-08T10:00:00Z", with_branch=True):
    msgs = [
        {"uuid": "m1", "parent_message_uuid": ROOT, "sender": "human", "index": 0,
         "created_at": "2026-11-08T09:00:00Z", "content": [{"type": "text", "text": "Make me an itinerary"}],
         "attachments": [{"file_name": "notes.txt", "file_type": "text/plain", "extracted_content": "Paris"}],
         "files_v2": [{"file_uuid": "f1", "file_name": "photo.png", "file_kind": "image",
                       "preview_url": "/api/org1/files/f1/preview"}]},
        {"uuid": "m2", "parent_message_uuid": "m1", "sender": "assistant", "index": 1,
         "created_at": "2026-11-08T09:01:00Z", "content": [
             {"type": "text", "text": "Here it is."},
             {"type": "tool_use", "name": "artifacts", "input": {
                 "id": "itinerary", "command": "create", "type": "text/markdown", "title": "Itinerary",
                 "content": "# Day 1\nLouvre"}}]},
        {"uuid": "m3", "parent_message_uuid": "m2", "sender": "human", "index": 2,
         "created_at": "2026-11-08T09:02:00Z", "content": [{"type": "text", "text": "Add Orsay"}]},
        {"uuid": "m4", "parent_message_uuid": "m3", "sender": "assistant", "index": 3,
         "created_at": "2026-11-08T09:03:00Z", "content": [
             {"type": "tool_use", "name": "artifacts", "input": {
                 "id": "itinerary", "command": "update", "old_str": "Louvre", "new_str": "Louvre, Orsay"}},
             {"type": "tool_use", "name": "create_file", "input": {
                 "path": "/mnt/user-data/outputs/budget.csv", "file_text": "item,eur\nhotel,300\n"}},
             {"type": "text", "text": "Updated."}]},
    ]
    if with_branch:
        msgs.append({"uuid": "m3b", "parent_message_uuid": "m2", "sender": "human", "index": 2,
                     "created_at": "2026-11-08T09:05:00Z",
                     "content": [{"type": "text", "text": "OLD BRANCH QUESTION"}]})
    return {"uuid": cid, "name": name, "created_at": "2026-11-08T09:00:00Z", "updated_at": updated,
            "model": "claude-opus-5-5", "current_leaf_message_uuid": "m4", "chat_messages": msgs}


def chatgpt_conv(cid="g1", title="Canvas test", update_time=1762600000.0):
    def node(nid, parent, children, role, content, recipient="all", meta=None, ctime=0.0):
        return {"id": nid, "parent": parent, "children": children,
                "message": None if role is None else {
                    "id": nid, "author": {"role": role}, "create_time": ctime, "recipient": recipient,
                    "content": content, "metadata": meta or {}}}

    canvas_create = '{"name": "Essay", "type": "document", "content": "Hello world"}'
    canvas_update = '{"updates": [{"pattern": "world", "multiple": false, "replacement": "there"}]}'
    mapping = {
        "root": node("root", None, ["sys"], None, None),
        "sys": node("sys", "root", ["u1"], "system", {"content_type": "text", "parts": [""]},
                    meta={"is_visually_hidden_from_conversation": True}, ctime=1.0),
        "u1": node("u1", "sys", ["a1"], "user", {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-UPLOAD1"}, "Write an essay"]},
            meta={"attachments": [{"id": "file-UPLOAD1", "name": "me.png"}]}, ctime=2.0),
        "a1": node("a1", "u1", ["t1"], "assistant", {"content_type": "text", "parts": [canvas_create]},
                   recipient="canmore.create_textdoc", ctime=3.0),
        "t1": node("t1", "a1", ["a2"], "tool", {"content_type": "text", "parts": [""]}, ctime=4.0),
        "a2": node("a2", "t1", ["a3"], "assistant", {"content_type": "text", "parts": [canvas_update]},
                   recipient="canmore.update_textdoc", ctime=5.0),
        "a3": node("a3", "a2", ["img"], "assistant", {"content_type": "text", "parts": [
            "Done. Download [data](sandbox:/mnt/data/out.csv)"]}, ctime=6.0),
        "img": node("img", "a3", ["a4", "a4b"], "tool", {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "sediment://file_GEN1"}]}, ctime=7.0),
        "a4": node("a4", "img", [], "assistant", {"content_type": "text", "parts": ["Here is the picture."]}, ctime=8.0),
        "a4b": node("a4b", "img", [], "assistant", {"content_type": "text", "parts": ["OLD BRANCH ANSWER"]}, ctime=7.5),
    }
    return {"conversation_id": cid, "title": title, "create_time": 1762590000.0, "update_time": update_time,
            "mapping": mapping, "current_node": "a4", "default_model_slug": "gpt-5"}
