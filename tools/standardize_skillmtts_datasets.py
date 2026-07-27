from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pyarrow.parquet as pq

DATASETS = ("rel-f1", "rel-stack", "rel-hm", "rel-event", "azure-pdm", "bdg2")


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def snake_case(value: str) -> str:
    value = value.strip().replace("Unnamed: 0", "source_row_id")
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return value.strip("_").lower()


def alias_select(columns: Iterable[str], overrides: dict[str, str] | None = None) -> str:
    overrides = overrides or {}
    aliases = []
    seen: set[str] = set()
    for column in columns:
        alias = overrides.get(column, snake_case(column))
        if alias in seen:
            raise ValueError(f"Duplicate normalized column name: {alias}")
        seen.add(alias)
        aliases.append(f"{quote_ident(column)} AS {quote_ident(alias)}")
    return ",\n       ".join(aliases)


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(8):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.25 * (attempt + 1))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Standardizer:
    def __init__(self, source_root: Path, output_root: Path, force: bool) -> None:
        self.source_root = source_root.resolve()
        self.output_root = output_root.resolve()
        self.force = force
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect()
        self.con.execute("SET threads = 4")
        self.con.execute("SET preserve_insertion_order = false")
        self.con.execute("SET memory_limit = '8GB'")

    def close(self) -> None:
        self.con.close()

    def scalar(self, query: str) -> Any:
        return self.con.execute(query).fetchone()[0]

    def find_directory(
        self,
        *,
        label: str,
        candidates: list[Path],
        recursive_pattern: str,
        required_files: list[str],
    ) -> Path:
        matches = [
            path
            for path in candidates
            if path.is_dir() and all((path / name).is_file() for name in required_files)
        ]
        matches.extend(
            path
            for path in self.source_root.glob(recursive_pattern)
            if path.is_dir() and all((path / name).is_file() for name in required_files)
        )
        unique = list(dict.fromkeys(path.resolve() for path in matches))
        if len(unique) != 1:
            raise FileNotFoundError(
                f"Expected exactly one prepared {label} directory containing "
                f"{required_files}; found {unique}"
            )
        return unique[0]

    def relbench_db(self, dataset: str, required_files: list[str]) -> Path:
        return self.find_directory(
            label=f"RelBench {dataset} database",
            candidates=[
                self.source_root / "relbench_cache" / dataset / "db",
                self.source_root / "rel_f1" / "relbench_cache" / dataset / "db",
            ],
            recursive_pattern=f"**/{dataset}/db",
            required_files=required_files,
        )

    def rows_parquet(self, path: Path) -> int:
        if path.is_dir():
            files = list(path.rglob("*.parquet"))
            return sum(pq.ParquetFile(file).metadata.num_rows for file in files)
        return pq.ParquetFile(path).metadata.num_rows

    def columns_parquet(self, path: Path) -> list[str]:
        file = next(path.rglob("*.parquet")) if path.is_dir() else path
        return pq.ParquetFile(file).schema_arrow.names

    def write_query(self, query: str, path: Path) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con.execute(
            f"COPY ({query}) TO {sql_string(path)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )
        return self.rows_parquet(path)

    def copy_parquet(
        self,
        source: Path,
        target: Path,
        *,
        where: str | None = None,
        overrides: dict[str, str] | None = None,
    ) -> int:
        columns = pq.ParquetFile(source).schema_arrow.names
        query = f"SELECT {alias_select(columns, overrides)} FROM read_parquet({sql_string(source)})"
        if where:
            query += f" WHERE {where}"
        return self.write_query(query, target)

    def profile_table(
        self,
        path: Path,
        *,
        primary_key: list[str] | None = None,
        foreign_keys: dict[str, str] | None = None,
        time_column: str | None = None,
        logical_path: str | None = None,
    ) -> dict[str, Any]:
        glob = str(path / "**" / "*.parquet") if path.is_dir() else str(path)
        if path.is_dir():
            logical_columns = [
                row[0]
                for row in self.con.execute(
                    f"DESCRIBE SELECT * FROM read_parquet({sql_string(glob)}, hive_partitioning=true)"
                ).fetchall()
            ]
        else:
            logical_columns = self.columns_parquet(path)
        profile: dict[str, Any] = {
            "path": logical_path or path.name,
            "format": "parquet",
            "rows": self.rows_parquet(path),
            "columns": logical_columns,
            "primary_key": primary_key or [],
            "foreign_keys": foreign_keys or {},
        }
        if path.is_file():
            profile["bytes"] = path.stat().st_size
            profile["sha256"] = sha256(path)
        else:
            files = list(path.rglob("*.parquet"))
            profile["files"] = len(files)
            profile["bytes"] = sum(file.stat().st_size for file in files)
        if time_column:
            low, high, missing = self.con.execute(
                f"SELECT MIN({quote_ident(time_column)}), MAX({quote_ident(time_column)}), "
                f"COUNT(*) FILTER (WHERE {quote_ident(time_column)} IS NULL) "
                f"FROM read_parquet({sql_string(glob)}, hive_partitioning=true)"
            ).fetchone()
            profile["time_column"] = time_column
            profile["time_range"] = {"min": str(low), "max": str(high)}
            profile["null_timestamps"] = missing
        return profile

    def staging(self, dataset: str) -> tuple[Path, Path]:
        final = self.output_root / dataset
        staging = self.output_root / f".{dataset}.staging.{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        if final.exists() and not self.force:
            raise FileExistsError(f"Output already exists: {final}. Use --force to replace it.")
        return staging, final

    def finish(self, staging: Path, final: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["validation"]["passed"] = all(
            item["passed"] for item in manifest["validation"]["checks"]
        )
        if not manifest["validation"]["passed"]:
            atomic_write_json(staging / "manifest.json", manifest)
            raise RuntimeError(f"Validation failed for {manifest['dataset_id']}")
        atomic_write_json(staging / "manifest.json", manifest)
        if final.exists():
            shutil.rmtree(final)
        os.replace(staging, final)
        manifest["local_path"] = str(final)
        return manifest

    @staticmethod
    def check(name: str, actual: Any, expected: Any) -> dict[str, Any]:
        return {"name": name, "actual": actual, "expected": expected, "passed": actual == expected}

    def base_manifest(self, dataset: str, source: str, notes: list[str]) -> dict[str, Any]:
        return {
            "dataset_id": dataset,
            "storage_format": "parquet",
            "naming_convention": "snake_case",
            "source": source,
            "notes": notes,
            "tables": {},
            "validation": {"passed": False, "checks": []},
        }

    def standardize_rel_f1(self) -> dict[str, Any]:
        dataset = "rel-f1"
        source_db = self.relbench_db(
            dataset,
            ["circuits.parquet", "drivers.parquet", "races.parquet", "results.parquet"],
        )
        staging, final = self.staging(dataset)
        tables = staging / "tables"
        relations = {
            "circuits": (["circuit_id"], {}),
            "constructors": (["constructor_id"], {}),
            "constructor_results": (["constructor_results_id"], {"race_id": "races.race_id", "constructor_id": "constructors.constructor_id"}),
            "constructor_standings": (["constructor_standings_id"], {"race_id": "races.race_id", "constructor_id": "constructors.constructor_id"}),
            "drivers": (["driver_id"], {}),
            "qualifying": (["qualify_id"], {"race_id": "races.race_id", "driver_id": "drivers.driver_id", "constructor_id": "constructors.constructor_id"}),
            "races": (["race_id"], {"circuit_id": "circuits.circuit_id"}),
            "results": (["result_id"], {"race_id": "races.race_id", "driver_id": "drivers.driver_id", "constructor_id": "constructors.constructor_id"}),
            "driver_standings": (["driver_standings_id"], {"race_id": "races.race_id", "driver_id": "drivers.driver_id"}),
        }
        source_names = {"driver_standings": "standings"}
        manifest = self.base_manifest(dataset, "RelBench rel-f1", ["Existing normalized relational structure retained; only names and storage are standardized."])
        for table, (pk, fks) in relations.items():
            source = source_db / f"{source_names.get(table, table)}.parquet"
            target = tables / f"{table}.parquet"
            rows = self.copy_parquet(source, target)
            manifest["validation"]["checks"].append(self.check(f"{table}_row_count", rows, pq.ParquetFile(source).metadata.num_rows))
            time_col = "date" if "date" in self.columns_parquet(target) else None
            manifest["tables"][table] = self.profile_table(target, primary_key=pk, foreign_keys=fks, time_column=time_col, logical_path=f"tables/{table}.parquet")
        return self.finish(staging, final, manifest)

    def standardize_rel_stack(self) -> dict[str, Any]:
        dataset = "rel-stack"
        source_db = self.relbench_db(
            dataset,
            ["users.parquet", "comments.parquet", "posts.parquet", "votes.parquet"],
        )
        staging, final = self.staging(dataset)
        tables = staging / "tables"
        manifest = self.base_manifest(dataset, "RelBench rel-stack", ["Posts are split semantically into questions, answers, and other post types."])

        simple = {
            "users": ("users", ["id"], {}, "creation_date"),
            "comments": ("comments", ["id"], {"post_id": "questions.id|answers.id|other_posts.id", "user_id": "users.id"}, "creation_date"),
            "votes": ("votes", ["id"], {"post_id": "questions.id|answers.id|other_posts.id", "user_id": "users.id"}, "creation_date"),
            "badges": ("badges", ["id"], {"user_id": "users.id"}, "date"),
            "post_links": ("postLinks", ["id"], {"post_id": "questions.id|answers.id|other_posts.id", "related_post_id": "questions.id|answers.id|other_posts.id"}, "creation_date"),
            "post_history": ("postHistory", ["id"], {"post_id": "questions.id|answers.id|other_posts.id", "user_id": "users.id"}, "creation_date"),
        }
        for table, (source_name, pk, fks, time_col) in simple.items():
            source = source_db / f"{source_name}.parquet"
            target = tables / f"{table}.parquet"
            rows = self.copy_parquet(source, target)
            manifest["validation"]["checks"].append(self.check(f"{table}_row_count", rows, pq.ParquetFile(source).metadata.num_rows))
            manifest["tables"][table] = self.profile_table(target, primary_key=pk, foreign_keys=fks, time_column=time_col, logical_path=f"tables/{table}.parquet")

        posts = source_db / "posts.parquet"
        split = {"questions": 1, "answers": 2}
        split_rows = 0
        for table, post_type in split.items():
            target = tables / f"{table}.parquet"
            rows = self.copy_parquet(posts, target, where=f'"PostTypeId" = {post_type}')
            split_rows += rows
            fks = {"owner_user_id": "users.id"}
            if table == "answers":
                fks["parent_id"] = "questions.id"
            manifest["tables"][table] = self.profile_table(target, primary_key=["id"], foreign_keys=fks, time_column="creation_date", logical_path=f"tables/{table}.parquet")
        other = tables / "other_posts.parquet"
        other_rows = self.copy_parquet(posts, other, where='"PostTypeId" NOT IN (1, 2) OR "PostTypeId" IS NULL')
        split_rows += other_rows
        manifest["tables"]["other_posts"] = self.profile_table(other, primary_key=["id"], foreign_keys={"owner_user_id": "users.id"}, time_column="creation_date", logical_path="tables/other_posts.parquet")
        manifest["validation"]["checks"].append(self.check("posts_split_row_conservation", split_rows, pq.ParquetFile(posts).metadata.num_rows))
        return self.finish(staging, final, manifest)

    def standardize_rel_hm(self) -> dict[str, Any]:
        dataset = "rel-hm"
        source_db = self.relbench_db(
            dataset,
            ["article.parquet", "customer.parquet", "transactions.parquet"],
        )
        staging, final = self.staging(dataset)
        tables = staging / "tables"
        manifest = self.base_manifest(dataset, "RelBench rel-hm", ["The wide article table is losslessly normalized into three reusable dimensions."])
        articles = source_db / "article.parquet"
        product_cols = ["product_type_no", "product_type_name", "product_group_name"]
        appearance_cols = ["graphical_appearance_no", "graphical_appearance_name", "colour_group_code", "colour_group_name", "perceived_colour_value_id", "perceived_colour_value_name", "perceived_colour_master_id", "perceived_colour_master_name"]
        merch_cols = ["department_no", "department_name", "index_code", "index_name", "index_group_no", "index_group_name", "section_no", "section_name", "garment_group_no", "garment_group_name"]

        dimensions: dict[str, tuple[str, list[str]]] = {
            "product_taxonomy": ("product_taxonomy_id", product_cols),
            "appearance": ("appearance_id", appearance_cols),
            "merchandising": ("merchandising_id", merch_cols),
        }
        for table, (id_col, columns) in dimensions.items():
            selected = ", ".join(quote_ident(column) for column in columns)
            aliases = alias_select(columns)
            query = f"WITH d AS (SELECT DISTINCT {selected} FROM read_parquet({sql_string(articles)})) SELECT ROW_NUMBER() OVER (ORDER BY {selected})::BIGINT AS {id_col}, {aliases} FROM d"
            target = tables / f"{table}.parquet"
            self.write_query(query, target)
            manifest["tables"][table] = self.profile_table(target, primary_key=[id_col], logical_path=f"tables/{table}.parquet")

        join_clauses = []
        for table, (id_col, columns) in dimensions.items():
            conditions = " AND ".join(f"a.{quote_ident(col)} IS NOT DISTINCT FROM d_{table}.{quote_ident(snake_case(col))}" for col in columns)
            join_clauses.append(f"JOIN read_parquet({sql_string(tables / (table + '.parquet'))}) d_{table} ON {conditions}")
        article_query = f"""
            SELECT a.article_id, a.product_code, a.prod_name,
                   d_product_taxonomy.product_taxonomy_id,
                   d_appearance.appearance_id,
                   d_merchandising.merchandising_id,
                   a.detail_desc
            FROM read_parquet({sql_string(articles)}) a
            {' '.join(join_clauses)}
        """
        article_target = tables / "articles.parquet"
        article_rows = self.write_query(article_query, article_target)
        source_article_rows = pq.ParquetFile(articles).metadata.num_rows
        manifest["validation"]["checks"].append(self.check("article_normalization_row_conservation", article_rows, source_article_rows))
        manifest["tables"]["articles"] = self.profile_table(article_target, primary_key=["article_id"], foreign_keys={"product_taxonomy_id": "product_taxonomy.product_taxonomy_id", "appearance_id": "appearance.appearance_id", "merchandising_id": "merchandising.merchandising_id"}, logical_path="tables/articles.parquet")

        for table, source_name, pk, fks, time_col in (
            ("customers", "customer", ["customer_id"], {}, None),
            ("transactions", "transactions", [], {"customer_id": "customers.customer_id", "article_id": "articles.article_id"}, "t_dat"),
        ):
            source = source_db / f"{source_name}.parquet"
            target = tables / f"{table}.parquet"
            rows = self.copy_parquet(source, target)
            manifest["validation"]["checks"].append(self.check(f"{table}_row_count", rows, pq.ParquetFile(source).metadata.num_rows))
            manifest["tables"][table] = self.profile_table(target, primary_key=pk, foreign_keys=fks, time_column=time_col, logical_path=f"tables/{table}.parquet")
        return self.finish(staging, final, manifest)

    def standardize_rel_event(self) -> dict[str, Any]:
        dataset = "rel-event"
        source_db = self.relbench_db(
            dataset,
            [
                "events.parquet",
                "users.parquet",
                "event_attendees.parquet",
                "event_interest.parquet",
                "user_friends.parquet",
            ],
        )
        staging, final = self.staging(dataset)
        tables = staging / "tables"
        manifest = self.base_manifest(dataset, "RelBench rel-event", ["Dense event feature columns are vertically separated from event identity and location fields without long-form expansion.", "Raw event timestamps include implausible values; task programs must declare a valid observation window."])

        events = source_db / "events.parquet"
        all_event_cols = pq.ParquetFile(events).schema_arrow.names
        feature_cols = [column for column in all_event_cols if re.fullmatch(r"c_(?:\d+|other)", column)]
        core_cols = [column for column in all_event_cols if column not in feature_cols]
        core = tables / "events.parquet"
        features = tables / "event_features.parquet"
        core_rows = self.write_query(f"SELECT {alias_select(core_cols)} FROM read_parquet({sql_string(events)})", core)
        feature_rows = self.write_query(f"SELECT event_id, {alias_select(feature_cols)} FROM read_parquet({sql_string(events)})", features)
        source_rows = pq.ParquetFile(events).metadata.num_rows
        manifest["validation"]["checks"].extend([
            self.check("events_core_row_count", core_rows, source_rows),
            self.check("event_features_one_to_one_row_count", feature_rows, source_rows),
        ])
        manifest["tables"]["events"] = self.profile_table(core, primary_key=["event_id"], foreign_keys={"user_id": "users.user_id"}, time_column="start_time", logical_path="tables/events.parquet")
        manifest["tables"]["event_features"] = self.profile_table(features, primary_key=["event_id"], foreign_keys={"event_id": "events.event_id"}, logical_path="tables/event_features.parquet")

        simple = {
            "users": ("users", {"joinedAt": "joined_at"}, ["user_id"], {}, "joined_at"),
            "event_attendees": ("event_attendees", {"Unnamed: 0": "attendee_record_id", "event": "event_id"}, ["attendee_record_id"], {"event_id": "events.event_id", "user_id": "users.user_id"}, "start_time"),
            "event_interest": ("event_interest", {"user": "user_id", "event": "event_id"}, [], {"event_id": "events.event_id", "user_id": "users.user_id"}, "timestamp"),
            "user_friends": ("user_friends", {"Unnamed: 0": "friendship_record_id", "user": "user_id", "friend": "friend_user_id"}, ["friendship_record_id"], {"user_id": "users.user_id", "friend_user_id": "users.user_id"}, None),
        }
        for table, (source_name, overrides, pk, fks, time_col) in simple.items():
            source = source_db / f"{source_name}.parquet"
            target = tables / f"{table}.parquet"
            rows = self.copy_parquet(source, target, overrides=overrides)
            manifest["validation"]["checks"].append(self.check(f"{table}_row_count", rows, pq.ParquetFile(source).metadata.num_rows))
            manifest["tables"][table] = self.profile_table(target, primary_key=pk, foreign_keys=fks, time_column=time_col, logical_path=f"tables/{table}.parquet")
        return self.finish(staging, final, manifest)

    def standardize_azure(self) -> dict[str, Any]:
        dataset = "azure-pdm"
        source_db = self.find_directory(
            label="Azure Predictive Maintenance source",
            candidates=[
                self.source_root / "azure-pdm",
                self.source_root / "azure_pdm",
                self.source_root / "azure_pdm" / "kaggle_mirror",
            ],
            recursive_pattern="**/azure-pdm",
            required_files=[
                "PdM_machines.csv",
                "PdM_telemetry.csv",
                "PdM_errors.csv",
                "PdM_maint.csv",
                "PdM_failures.csv",
            ],
        )
        staging, final = self.staging(dataset)
        tables = staging / "tables"
        manifest = self.base_manifest(dataset, "Microsoft Azure Predictive Maintenance public five-table mirror", ["The five-table relational structure is retained because it already matches machine, telemetry, error, maintenance, and failure semantics."])
        specs = {
            "machines": ("PdM_machines.csv", ["machine_id"], {}, None),
            "telemetry": ("PdM_telemetry.csv", [], {"machine_id": "machines.machine_id"}, "datetime"),
            "errors": ("PdM_errors.csv", [], {"machine_id": "machines.machine_id"}, "datetime"),
            "maintenance": ("PdM_maint.csv", [], {"machine_id": "machines.machine_id"}, "datetime"),
            "failures": ("PdM_failures.csv", [], {"machine_id": "machines.machine_id"}, "datetime"),
        }
        for table, (filename, pk, fks, time_col) in specs.items():
            source = source_db / filename
            description = self.con.execute(f"DESCRIBE SELECT * FROM read_csv_auto({sql_string(source)}, header=true)").fetchall()
            columns = [row[0] for row in description]
            overrides = {"machineID": "machine_id"}
            expressions = []
            for column in columns:
                alias = overrides.get(column, snake_case(column))
                if column == "datetime":
                    expressions.append(f"CAST({quote_ident(column)} AS TIMESTAMP) AS datetime")
                else:
                    expressions.append(f"{quote_ident(column)} AS {quote_ident(alias)}")
            query = f"SELECT {', '.join(expressions)} FROM read_csv_auto({sql_string(source)}, header=true)"
            target = tables / f"{table}.parquet"
            rows = self.write_query(query, target)
            source_rows = self.scalar(f"SELECT COUNT(*) FROM read_csv_auto({sql_string(source)}, header=true)")
            manifest["validation"]["checks"].append(self.check(f"{table}_row_count", rows, source_rows))
            manifest["tables"][table] = self.profile_table(target, primary_key=pk, foreign_keys=fks, time_column=time_col, logical_path=f"tables/{table}.parquet")
        return self.finish(staging, final, manifest)

    def standardize_bdg2(self) -> dict[str, Any]:
        dataset = "bdg2"
        source_db = self.find_directory(
            label="BDG2 v1.0 data",
            candidates=[],
            recursive_pattern="**/buds-lab-building-data-genome-project-2-*/data",
            required_files=["metadata/metadata.csv", "weather/weather.csv"],
        )
        staging, final = self.staging(dataset)
        tables = staging / "tables"
        manifest = self.base_manifest(dataset, "Building Data Genome 2 v1.0", ["Wide meter matrices are converted to a canonical long relation and physically partitioned by cleaning_state, meter_type, and year.", "Raw and cleaned readings are both retained to support data-quality tasks."])

        metadata = source_db / "metadata" / "metadata.csv"
        meta_desc = self.con.execute(f"DESCRIBE SELECT * FROM read_csv_auto({sql_string(metadata)}, header=true, sample_size=-1)").fetchall()
        meta_cols = [row[0] for row in meta_desc]
        buildings = tables / "buildings.parquet"
        building_rows = self.write_query(f"SELECT {alias_select(meta_cols)} FROM read_csv_auto({sql_string(metadata)}, header=true, sample_size=-1)", buildings)
        source_building_rows = self.scalar(f"SELECT COUNT(*) FROM read_csv_auto({sql_string(metadata)}, header=true, sample_size=-1)")
        manifest["validation"]["checks"].append(self.check("buildings_row_count", building_rows, source_building_rows))
        manifest["tables"]["buildings"] = self.profile_table(buildings, primary_key=["building_id"], logical_path="tables/buildings.parquet")

        sites = tables / "sites.parquet"
        site_query = f"""
            SELECT site_id,
                   MIN(lat) FILTER (WHERE lat IS NOT NULL) AS lat,
                   MIN(lng) FILTER (WHERE lng IS NOT NULL) AS lng,
                   MIN(timezone) FILTER (WHERE timezone IS NOT NULL) AS timezone,
                   COUNT(*) AS building_count,
                   COUNT(DISTINCT lat) AS distinct_lat_count,
                   COUNT(DISTINCT lng) AS distinct_lng_count,
                   COUNT(DISTINCT timezone) AS distinct_timezone_count
            FROM read_parquet({sql_string(buildings)}) GROUP BY site_id
        """
        self.write_query(site_query, sites)
        conflicts = self.scalar(f"SELECT COUNT(*) FROM read_parquet({sql_string(sites)}) WHERE distinct_lat_count > 1 OR distinct_lng_count > 1 OR distinct_timezone_count > 1")
        manifest["validation"]["checks"].append(self.check("site_attributes_are_consistent", conflicts, 0))
        manifest["tables"]["sites"] = self.profile_table(sites, primary_key=["site_id"], logical_path="tables/sites.parquet")

        weather_source = source_db / "weather" / "weather.csv"
        weather_desc = self.con.execute(f"DESCRIBE SELECT * FROM read_csv_auto({sql_string(weather_source)}, header=true, sample_size=-1)").fetchall()
        weather_cols = [row[0] for row in weather_desc]
        weather_expr = []
        for column in weather_cols:
            if column == "timestamp":
                weather_expr.append("CAST(timestamp AS TIMESTAMP) AS timestamp")
            else:
                weather_expr.append(f"{quote_ident(column)} AS {quote_ident(snake_case(column))}")
        weather = tables / "weather_hourly.parquet"
        weather_rows = self.write_query(f"SELECT {', '.join(weather_expr)} FROM read_csv_auto({sql_string(weather_source)}, header=true, sample_size=-1)", weather)
        source_weather_rows = self.scalar(f"SELECT COUNT(*) FROM read_csv_auto({sql_string(weather_source)}, header=true, sample_size=-1)")
        manifest["validation"]["checks"].append(self.check("weather_row_count", weather_rows, source_weather_rows))
        manifest["tables"]["weather_hourly"] = self.profile_table(weather, foreign_keys={"site_id": "sites.site_id"}, time_column="timestamp", logical_path="tables/weather_hourly.parquet")

        meter_root = tables / "meter_readings"
        meter_source_files = []
        expected_partitions = 0
        for cleaning_state in ("raw", "cleaned"):
            for source in sorted((source_db / "meters" / cleaning_state).glob("*.csv")):
                meter_type = source.stem.replace("_cleaned", "")
                meter_source_files.append((cleaning_state, meter_type, source))
                expected_partitions += 2
                query = f"""
                    SELECT CAST(timestamp AS TIMESTAMP) AS timestamp,
                           CAST(building_id AS VARCHAR) AS building_id,
                           TRY_CAST(reading AS DOUBLE) AS reading,
                           {sql_string(cleaning_state)} AS cleaning_state,
                           {sql_string(meter_type)} AS meter_type,
                           YEAR(CAST(timestamp AS TIMESTAMP))::INTEGER AS year
                    FROM (
                        UNPIVOT read_csv({sql_string(source)}, header=true, all_varchar=true)
                        ON COLUMNS(* EXCLUDE (timestamp))
                        INTO NAME building_id VALUE reading
                    )
                    WHERE TRY_CAST(reading AS DOUBLE) IS NOT NULL
                """
                self.con.execute(
                    f"COPY ({query}) TO {sql_string(meter_root)} "
                    "(FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (cleaning_state, meter_type, year), "
                    "OVERWRITE_OR_IGNORE, ROW_GROUP_SIZE 100000)"
                )

        parquet_files = list(meter_root.rglob("*.parquet"))
        actual_partitions = len({file.parent for file in parquet_files})
        manifest["validation"]["checks"].append(self.check("meter_partition_count", actual_partitions, expected_partitions))
        meter_rows = self.rows_parquet(meter_root)
        manifest["validation"]["checks"].append({"name": "meter_readings_nonempty", "actual": meter_rows, "expected": "> 0", "passed": meter_rows > 0})
        manifest["tables"]["meter_readings"] = self.profile_table(meter_root, foreign_keys={"building_id": "buildings.building_id"}, time_column="timestamp", logical_path="tables/meter_readings/cleaning_state=*/meter_type=*/year=*/*.parquet")
        manifest["tables"]["meter_readings"]["partition_columns"] = ["cleaning_state", "meter_type", "year"]
        manifest["tables"]["meter_readings"]["source_matrices"] = [f"{state}/{path.name}" for state, _, path in meter_source_files]
        return self.finish(staging, final, manifest)

    def run(self, datasets: list[str]) -> list[dict[str, Any]]:
        methods = {
            "rel-f1": self.standardize_rel_f1,
            "rel-stack": self.standardize_rel_stack,
            "rel-hm": self.standardize_rel_hm,
            "rel-event": self.standardize_rel_event,
            "azure-pdm": self.standardize_azure,
            "bdg2": self.standardize_bdg2,
        }
        results = []
        for dataset in datasets:
            print(f"[start] {dataset}", flush=True)
            result = methods[dataset]()
            results.append(result)
            print(f"[done] {dataset}: {len(result['tables'])} tables", flush=True)
        catalog_items = []
        for dataset in DATASETS:
            manifest_path = self.output_root / dataset / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            catalog_items.append(
                {
                    "dataset_id": dataset,
                    "path": str(self.output_root / dataset),
                    "table_count": len(manifest["tables"]),
                    "validation_passed": manifest["validation"]["passed"],
                }
            )
        catalog = {
            "version": 1,
            "datasets": catalog_items,
        }
        atomic_write_json(self.output_root / "catalog.json", catalog)
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standardize and semantically split SkillMTTS datasets.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--datasets", nargs="+", choices=(*DATASETS, "all"), default=["all"])
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = list(DATASETS) if "all" in args.datasets else args.datasets
    standardizer = Standardizer(args.source_root, args.output_root, args.force)
    try:
        standardizer.run(datasets)
    finally:
        standardizer.close()


if __name__ == "__main__":
    main()
