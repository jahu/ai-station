"""Physical/default references survive logical model identity migration."""

import pytest
from alembic import command
from app.db import alembic_config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_0044_keeps_legacy_selection_and_requires_lossless_downgrade(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "bindings.sqlite"))
    config = alembic_config()
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "0043")
        db.exec_driver_sql(
            "INSERT INTO model_files(id,host_path,filename,size_bytes,mtime,format,family,quantization,category,capabilities,root_label,discovered_at,availability) VALUES ('file','/external/existing.gguf','existing.gguf',1024,1,'gguf','qwen3','Q4','llm','[]','/external',CURRENT_TIMESTAMP,'present')"
        )
        db.exec_driver_sql(
            "INSERT INTO model_definitions(id,file_id,name,family,category,capabilities,status,metadata,created_at,updated_at) VALUES ('legacy','file','Existing','qwen3','llm','[]','registered','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        )
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "0044")
        assert db.execute(
            text("SELECT file_id,binding_key FROM model_definitions WHERE id='legacy'")
        ).one() == ("file", None)
        db.exec_driver_sql(
            "INSERT INTO model_definitions(id,file_id,binding_key,name,family,category,capabilities,status,metadata,created_at,updated_at) VALUES ('second','file','content-identity','Additional','qwen3','llm','[]','registered','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        )
        assert not db.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    for identity, key in [("duplicate-default", None), ("duplicate-binding", "content-identity")]:
        with pytest.raises(IntegrityError), engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO model_definitions(id,file_id,binding_key,name,family,category,capabilities,status,metadata,created_at,updated_at) VALUES (:id,'file',:key,'Duplicate','qwen3','llm','[]','registered','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {"id": identity, "key": key},
            )
    with pytest.raises(RuntimeError, match="additional logical"), engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "0043")
    with engine.begin() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0044"
        db.exec_driver_sql("DELETE FROM model_definitions WHERE id='second'")
        config.attributes["connection"] = db
        command.downgrade(config, "0043")
        assert db.scalar(text("SELECT file_id FROM model_definitions WHERE id='legacy'")) == "file"
    engine.dispose()
