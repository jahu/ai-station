import pytest
from alembic import command
from app.db import alembic_config
from sqlalchemy import create_engine, text


def test_0042_preserves_external_file_and_definition_references_in_both_directions(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.sqlite"))
    cfg = alembic_config()
    with engine.begin() as db:
        cfg.attributes["connection"] = db
        command.upgrade(cfg, "0041")
        db.execute(
            text(
                "INSERT INTO model_files(id,host_path,filename,size_bytes,mtime,format,family,quantization,category,capabilities,root_label,discovered_at,availability) VALUES ('file','/external/existing.gguf','existing.gguf',1024,1,'gguf','qwen3','Q4','llm','[]','/external',CURRENT_TIMESTAMP,'present')"
            )
        )
        db.execute(
            text(
                "INSERT INTO model_definitions(id,file_id,name,family,category,capabilities,status,metadata,created_at,updated_at) VALUES ('definition','file','Existing','qwen3','llm','[]','registered','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    with engine.begin() as db:
        cfg.attributes["connection"] = db
        command.upgrade(cfg, "head")
        assert db.execute(
            text("SELECT host_path,relative_path,sha256 FROM model_files WHERE id='file'")
        ).one() == ("/external/existing.gguf", None, None)
        assert db.scalar(text("SELECT file_id FROM model_definitions WHERE id='definition'")) == "file"
        assert not db.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    with engine.begin() as db:
        cfg.attributes["connection"] = db
        command.downgrade(cfg, "0041")
        assert (
            db.scalar(text("SELECT host_path FROM model_files WHERE id='file'")) == "/external/existing.gguf"
        )
        assert db.scalar(text("SELECT file_id FROM model_definitions WHERE id='definition'")) == "file"
    engine.dispose()


def test_downgrade_preserves_owned_models_by_refusing_to_drop_their_coordinates(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "owned.sqlite"))
    cfg = alembic_config()
    with engine.begin() as db:
        cfg.attributes["connection"] = db
        command.upgrade(cfg, "head")
        db.execute(
            text(
                "INSERT INTO model_files(id,relative_path,sha256,filename,size_bytes,mtime,format,family,quantization,category,capabilities,root_label,discovered_at,availability) VALUES ('owned',:path,:sha,'owned.gguf',1024,1,'gguf','qwen3','Q4','llm','[]','AI Station storage',CURRENT_TIMESTAMP,'present')"
            ),
            {"path": "models/store/" + "a" * 64, "sha": "a" * 64},
        )
    with pytest.raises(RuntimeError, match="Keep installed model identities"), engine.begin() as db:
        cfg.attributes["connection"] = db
        command.downgrade(cfg, "0041")
    with engine.connect() as db:
        assert (
            db.scalar(text("SELECT relative_path FROM model_files WHERE id='owned'"))
            == "models/store/" + "a" * 64
        )
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0042"
    engine.dispose()
