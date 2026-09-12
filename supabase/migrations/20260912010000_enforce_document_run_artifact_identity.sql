-- ============================================================
-- Integridad relacional de la procedencia documental (Bloque 4.1.b)
--
-- El modelo del Bloque 4.0/4.1 ya exige que `document_versions.document_id`,
-- `run_id` y `source_artifact_id` apunten a filas existentes, y que una
-- corrida no se reutilice (`unique (run_id)`). Ninguna de esas reglas exige
-- que los tres identificadores describan **la misma ingesta**.
--
-- Con el esquema anterior, un escritor SQL podía guardar una versión del
-- documento B citando la corrida del documento A, o citar un archivo que no
-- es el que esa corrida procesó. Los tres identificadores serían válidos por
-- separado, y `document_chunk_provenance` uniría filas reales con atribución
-- falsa: el chunk diría venir de un archivo que nadie ingirió para él. Si el
-- documento citado pertenece a otro alcance, la cita atribuye contenido al
-- alcance equivocado.
--
-- Las validaciones y los locks del adaptador protegen las operaciones del
-- adaptador. No protegen frente a otro escritor, ni frente a un `update`
-- posterior. Una garantía permanente de la procedencia es del esquema
-- (ADR 0001: el esquema solo cambia por migración versionada).
--
-- QUÉ NO HACE, y no es un olvido:
--
-- `elsa.source_artifacts` es un registro direccionado por contenido —tipo,
-- sha256, tamaño, clave de almacenamiento— y **no tiene dominio, activo ni
-- documento**. No hay en el esquema información con la que exigir que un
-- archivo «pertenezca» a un documento, y no debe haberla: el mismo archivo
-- puede ingerirse legítimamente más de una vez. El cruce entre dominios y
-- activos ya lo impide `fk_document_asset`, que ata `(asset_id, domain)` del
-- documento al activo. Lo que esta migración cierra es el eslabón que
-- faltaba: documento ↔ corrida ↔ archivo.
--
-- No modifica la migración 20260908010000, ya aplicada. No toca datos, RLS,
-- políticas, vistas ni privilegios.
-- ============================================================

-- Clave candidata compuesta sobre la corrida. `id` ya es la clave primaria,
-- así que esta unicidad no restringe nada nuevo: existe porque PostgreSQL
-- exige una clave única sobre las columnas exactas a las que apunta una
-- clave foránea compuesta.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'elsa.document_ingestion_runs'::regclass
      and conname = 'uq_document_run_identity'
  ) then
    alter table elsa.document_ingestion_runs
      add constraint uq_document_run_identity
      unique (id, document_id, source_artifact_id);
  end if;
end;
$$;

-- La versión ya no cita tres identificadores sueltos, sino la tupla completa
-- de una corrida real.
--
-- `on update restrict` es la mitad que cierra el agujero en el tiempo:
-- impide mover después el documento o el archivo de una corrida ya citada,
-- que convertiría en falsa una procedencia que era verdadera.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'elsa.document_versions'::regclass
      and conname = 'fk_document_version_run_identity'
  ) then
    alter table elsa.document_versions
      add constraint fk_document_version_run_identity
      foreign key (run_id, document_id, source_artifact_id)
      references elsa.document_ingestion_runs (id, document_id, source_artifact_id)
      on update restrict on delete restrict;
  end if;
end;
$$;

comment on constraint fk_document_version_run_identity on elsa.document_versions is
  'La versión, su corrida y su archivo describen la misma ingesta. La procedencia no puede mentir.';
