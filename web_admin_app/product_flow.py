import json

from web_admin_app.database import get_conn, now_text, row_to_dict


ACTIVE_STATUS = "active"


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "是")


def int_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        items = value
    else:
        try:
            items = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            items = str(value).split(",")
    result = []
    for item in items:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number and number not in result:
            result.append(number)
    return result


def json_ids(value):
    return json.dumps(int_list(value), ensure_ascii=False)


def alias_row(conn, barcode):
    return conn.execute(
        """
        SELECT barcode_aliases.id AS alias_id, barcode_aliases.product_instance_id,
               barcode_aliases.barcode, barcode_aliases.barcode_type,
               barcode_aliases.is_current, barcode_aliases.disabled_at,
               product_instances.project_id, product_instances.material_code,
               product_instances.product_type, product_instances.current_barcode,
               product_instances.status, product_instances.created_at,
               product_instances.updated_at
        FROM barcode_aliases
        JOIN product_instances ON product_instances.id = barcode_aliases.product_instance_id
        WHERE barcode_aliases.barcode = ?
        """,
        (barcode,),
    ).fetchone()


def instance_row(conn, product_instance_id):
    return conn.execute(
        "SELECT * FROM product_instances WHERE id = ?",
        (product_instance_id,),
    ).fetchone()


def public_identity(row):
    data = row_to_dict(row)
    if not data:
        return None
    data["is_current"] = bool(data.get("is_current", False))
    legacy_allowed = not data["is_current"] and data.get("disabled_at") is None
    data["allowed_production"] = (
        data.get("status") == ACTIVE_STATUS
        and (
            (
                data["is_current"]
                and data.get("barcode") == data.get("current_barcode")
            )
            or legacy_allowed
        )
    )
    if legacy_allowed:
        data["message"] = (
            f"旧条码已映射到当前主条码 {data.get('current_barcode', '')}"
        )
    elif not data["allowed_production"] and not data["is_current"]:
        data["message"] = (
            f"该条码已切换为新主条码 {data.get('current_barcode', '')}，"
            "请扫描当前主条码"
        )
    elif data.get("status") != ACTIVE_STATUS:
        data["message"] = "当前产品状态异常，禁止生产"
    else:
        data["message"] = "条码有效"
    return data


def create_product_instance(
    conn,
    project_id,
    barcode,
    material_code="",
    product_type="",
    barcode_type="main_current",
):
    if not barcode:
        raise ValueError("条码不能为空")
    if alias_row(conn, barcode):
        raise ValueError("条码已被其他产品使用")
    now = now_text()
    cursor = conn.execute(
        """
        INSERT INTO product_instances
        (project_id, material_code, product_type, current_barcode, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(project_id),
            material_code or "",
            product_type or material_code or "",
            barcode,
            ACTIVE_STATUS,
            now,
            now,
        ),
    )
    product_instance_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO barcode_aliases
        (product_instance_id, barcode, barcode_type, is_current, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (product_instance_id, barcode, barcode_type, True, now),
    )
    return alias_row(conn, barcode)


def resolve_barcode(payload):
    barcode = str(payload.get("barcode", "")).strip()
    if not barcode:
        raise ValueError("条码不能为空")
    with get_conn() as conn:
        row = alias_row(conn, barcode)
        if not row and as_bool(payload.get("create_if_missing")):
            project_id = int(payload.get("project_id", 0))
            if not project_id:
                raise ValueError("创建产品实体时 project_id 不能为空")
            row = create_product_instance(
                conn,
                project_id,
                barcode,
                payload.get("material_code", ""),
                payload.get("product_type", ""),
                payload.get("barcode_type", "main_current"),
            )
        if not row:
            return {
                "ok": False,
                "found": False,
                "allowed_production": False,
                "message": "未找到该条码对应的产品实体",
            }
        data = public_identity(row)
        data.update({"ok": True, "found": True})
        return data


def ensure_product_for_completion(conn, payload, project_id, barcode):
    product_instance_id = payload.get("product_instance_id")
    if product_instance_id:
        row = instance_row(conn, int(product_instance_id))
        if not row:
            raise ValueError("产品实体不存在")
        return int(product_instance_id)
    alias = alias_row(conn, barcode)
    if alias:
        return int(alias["product_instance_id"])
    return int(
        create_product_instance(
            conn,
            project_id,
            barcode,
            payload.get("material_code", ""),
            payload.get("product_type", ""),
        )["product_instance_id"]
    )


def completion_exists(conn, product_instance_id, station_id, legacy_barcode=""):
    row = conn.execute(
        """
        SELECT 1 FROM station_completions
        WHERE station_id = ?
          AND (
            product_instance_id = ?
            OR (product_instance_id IS NULL AND barcode = ?)
          )
        LIMIT 1
        """,
        (station_id, product_instance_id, legacy_barcode),
    ).fetchone()
    return row is not None


def previous_station_id(conn, project_id, station_id):
    rows = conn.execute(
        "SELECT id FROM stations WHERE project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()
    ids = [int(row["id"]) for row in rows]
    try:
        index = ids.index(int(station_id))
    except ValueError:
        return None
    return ids[index - 1] if index > 0 else None


def get_station_dependency(station_id):
    with get_conn() as conn:
        return _station_dependency(conn, station_id)


def _station_dependency(conn, station_id):
    row = conn.execute(
        "SELECT * FROM station_dependencies WHERE station_id = ?",
        (station_id,),
    ).fetchone()
    if not row:
        return {
            "station_id": int(station_id),
            "require_previous_station": True,
            "required_station_ids": [],
            "require_barcode_switch": False,
            "require_current_barcode": False,
            "required_child_project_id": None,
            "required_child_material_type": "",
            "required_child_count": 0,
            "required_child_station_ids": [],
        }
    data = row_to_dict(row)
    data["require_previous_station"] = bool(data["require_previous_station"])
    data["require_barcode_switch"] = bool(data["require_barcode_switch"])
    data["require_current_barcode"] = bool(data["require_current_barcode"])
    data["required_station_ids"] = int_list(data["required_station_ids"])
    data["required_child_station_ids"] = int_list(data["required_child_station_ids"])
    return data


def save_station_dependency(station_id, payload):
    station_id = int(station_id)
    now = now_text()
    required_station_ids = int_list(payload.get("required_station_ids"))
    child_project_id = int(payload.get("required_child_project_id") or 0) or None
    child_station_ids = int_list(payload.get("required_child_station_ids"))
    values = (
        as_bool(payload.get("require_previous_station"), True),
        json_ids(required_station_ids),
        as_bool(payload.get("require_barcode_switch"), False),
        as_bool(payload.get("require_current_barcode"), False),
        child_project_id,
        str(payload.get("required_child_material_type", "")).strip(),
        max(int(payload.get("required_child_count") or 0), 0),
        json_ids(child_station_ids),
        now,
        station_id,
    )
    with get_conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM stations WHERE id = ?", (station_id,)
        ).fetchone():
            raise ValueError("当前工位不存在")
        for required_station_id in required_station_ids:
            if not conn.execute(
                "SELECT 1 FROM stations WHERE id = ?", (required_station_id,)
            ).fetchone():
                raise ValueError(f"指定前置工位不存在：{required_station_id}")
        if child_project_id and not conn.execute(
            "SELECT 1 FROM projects WHERE id = ?", (child_project_id,)
        ).fetchone():
            raise ValueError("子物料项目不存在")
        for child_station_id in child_station_ids:
            row = conn.execute(
                "SELECT project_id FROM stations WHERE id = ?",
                (child_station_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"子物料要求工位不存在：{child_station_id}")
            if child_project_id and int(row["project_id"]) != child_project_id:
                raise ValueError("子物料要求工位不属于所选子物料项目")
        existing = conn.execute(
            "SELECT id FROM station_dependencies WHERE station_id = ?",
            (station_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE station_dependencies
                SET require_previous_station = ?, required_station_ids = ?,
                    require_barcode_switch = ?, require_current_barcode = ?,
                    required_child_project_id = ?,
                    required_child_material_type = ?, required_child_count = ?,
                    required_child_station_ids = ?, updated_at = ?
                WHERE station_id = ?
                """,
                values,
            )
        else:
            conn.execute(
                """
                INSERT INTO station_dependencies
                (require_previous_station, required_station_ids, require_barcode_switch,
                 require_current_barcode, required_child_project_id,
                 required_child_material_type,
                 required_child_count, required_child_station_ids, updated_at,
                 station_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, now),
            )
    return get_station_dependency(station_id)


def _verify_station_entry(conn, product, station_id, barcode=""):
    station = conn.execute(
        "SELECT id, project_id, name FROM stations WHERE id = ?",
        (station_id,),
    ).fetchone()
    if not station:
        return False, "工位不存在", []
    if product["status"] != ACTIVE_STATUS:
        return False, "当前产品状态异常，禁止生产", []
    dependency = _station_dependency(conn, station_id)
    failed = []
    if (
        dependency["require_current_barcode"]
        and barcode
        and barcode != product["current_barcode"]
    ):
        failed.append(f"必须使用当前有效主条码：{product['current_barcode']}")
    if dependency["require_previous_station"]:
        previous_id = previous_station_id(conn, station["project_id"], station_id)
        if previous_id and not completion_exists(
            conn, product["id"], previous_id, product["current_barcode"]
        ):
            failed.append("上一工位未完成")
    for required_station_id in dependency["required_station_ids"]:
        if not completion_exists(
            conn,
            product["id"],
            required_station_id,
            product["current_barcode"],
        ):
            required = conn.execute(
                "SELECT name FROM stations WHERE id = ?",
                (required_station_id,),
            ).fetchone()
            failed.append(
                f"指定工位未完成：{required['name'] if required else required_station_id}"
            )
    if dependency["require_barcode_switch"]:
        switched = conn.execute(
            "SELECT 1 FROM barcode_switch_records WHERE product_instance_id = ? LIMIT 1",
            (product["id"],),
        ).fetchone()
        if not switched:
            failed.append("主条码切换未完成")
    required_child_count = dependency["required_child_count"]
    if required_child_count > 0:
        bindings = conn.execute(
            """
            SELECT material_bindings.*, product_instances.project_id AS child_project_id,
                   product_instances.product_type AS child_product_type,
                   product_instances.current_barcode AS child_current_barcode
            FROM material_bindings
            JOIN product_instances
              ON product_instances.id = material_bindings.child_product_instance_id
            WHERE material_bindings.parent_product_instance_id = ?
              AND material_bindings.is_active = ?
            """,
            (product["id"], True),
        ).fetchall()
        valid_children = []
        for binding in bindings:
            if (
                dependency["required_child_project_id"]
                and int(binding["child_project_id"])
                != int(dependency["required_child_project_id"])
            ):
                continue
            if (
                dependency["required_child_material_type"]
                and binding["child_product_type"]
                != dependency["required_child_material_type"]
            ):
                continue
            if all(
                completion_exists(
                    conn,
                    binding["child_product_instance_id"],
                    child_station_id,
                    binding["child_current_barcode"],
                )
                for child_station_id in dependency["required_child_station_ids"]
            ):
                valid_children.append(binding)
        if len(valid_children) < required_child_count:
            failed.append(
                f"符合要求的子物料不足：需要{required_child_count}件，当前{len(valid_children)}件"
            )
    if failed:
        return False, "；".join(failed), failed
    return True, "允许进入当前工位", []


def verify_station_entry(payload):
    station_id = int(payload.get("station_id", 0))
    if not station_id:
        raise ValueError("station_id 不能为空")
    with get_conn() as conn:
        product_instance_id = payload.get("product_instance_id")
        product = (
            instance_row(conn, int(product_instance_id))
            if product_instance_id
            else None
        )
        if not product and payload.get("barcode"):
            alias = alias_row(conn, payload["barcode"])
            product = (
                instance_row(conn, alias["product_instance_id"]) if alias else None
            )
        if not product:
            return {"allowed": False, "message": "未找到产品实体", "failed": ["未找到产品实体"]}
        allowed, message, failed = _verify_station_entry(
            conn,
            product,
            station_id,
            str(payload.get("barcode") or product["current_barcode"]),
        )
        return {
            "allowed": allowed,
            "message": message,
            "failed": failed,
            "product_instance_id": product["id"],
            "current_barcode": product["current_barcode"],
        }


def switch_main_barcode(payload):
    old_barcode = str(payload.get("old_barcode", "")).strip()
    new_barcode = str(payload.get("new_barcode", "")).strip()
    if not old_barcode or not new_barcode:
        raise ValueError("旧主条码和新主条码不能为空")
    if old_barcode == new_barcode:
        raise ValueError("新主条码不能与旧主条码相同")
    with get_conn() as conn:
        old_alias = alias_row(conn, old_barcode)
        if not old_alias:
            raise ValueError("旧主条码不存在")
        if not bool(old_alias["is_current"]) or old_alias["current_barcode"] != old_barcode:
            raise ValueError(
                f"旧条码已失效，请扫描当前主条码 {old_alias['current_barcode']}"
            )
        if payload.get("product_instance_id") and int(payload["product_instance_id"]) != int(
            old_alias["product_instance_id"]
        ):
            raise ValueError("旧主条码不属于当前产品")
        if alias_row(conn, new_barcode):
            raise ValueError("新主条码已被其他产品使用")
        station_id = int(payload.get("station_id", 0))
        if station_id:
            product = instance_row(conn, old_alias["product_instance_id"])
            allowed, message, _failed = _verify_station_entry(conn, product, station_id)
            if not allowed:
                raise ValueError(message)
        now = now_text()
        disable_old = as_bool(payload.get("disable_old", True), True)
        set_current = as_bool(payload.get("set_current", True), True)
        conn.execute(
            """
            UPDATE barcode_aliases
            SET is_current = ?, barcode_type = 'main_old', disabled_at = ?
            WHERE id = ?
            """,
            (
                not set_current,
                now if set_current and disable_old else None,
                old_alias["alias_id"],
            ),
        )
        conn.execute(
            """
            INSERT INTO barcode_aliases
            (product_instance_id, barcode, barcode_type, is_current, created_at)
            VALUES (?, ?, 'main_current', ?, ?)
            """,
            (
                old_alias["product_instance_id"],
                new_barcode,
                set_current,
                now,
            ),
        )
        if set_current:
            conn.execute(
                """
                UPDATE product_instances
                SET current_barcode = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_barcode, now, old_alias["product_instance_id"]),
            )
        current_barcode = new_barcode if set_current else old_barcode
        conn.execute(
            """
            INSERT INTO barcode_switch_records
            (product_instance_id, old_barcode, new_barcode, project_id,
             station_id, step_id, operator, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                old_alias["product_instance_id"],
                old_barcode,
                new_barcode,
                int(payload.get("project_id") or old_alias["project_id"]),
                station_id,
                int(payload.get("step_id") or 0) or None,
                payload.get("operator", ""),
                payload.get("reason", ""),
                now,
            ),
        )
    return {
        "ok": True,
        "product_instance_id": old_alias["product_instance_id"],
        "old_barcode": old_barcode,
        "current_barcode": current_barcode,
        "message": (
            f"主条码已从 {old_barcode} 切换为 {new_barcode}"
            if set_current
            else f"新条码 {new_barcode} 已绑定，当前主条码仍为 {old_barcode}"
        ),
    }


def bind_child_material(payload):
    parent_barcode = str(payload.get("parent_barcode", "")).strip()
    child_barcode = str(payload.get("child_barcode", "")).strip()
    if not parent_barcode or not child_barcode:
        raise ValueError("父件主条码和子件主条码不能为空")
    with get_conn() as conn:
        parent = alias_row(conn, parent_barcode)
        child = alias_row(conn, child_barcode)
        if not parent or not public_identity(parent)["allowed_production"]:
            raise ValueError("父件主条码无效或不是当前主条码")
        if not child or not public_identity(child)["allowed_production"]:
            raise ValueError("子物料主条码无效或不是当前主条码")
        if parent["product_instance_id"] == child["product_instance_id"]:
            raise ValueError("父件和子件不能是同一个产品实体")
        if as_bool(payload.get("require_parent_switch"), True):
            switched = conn.execute(
                "SELECT 1 FROM barcode_switch_records WHERE product_instance_id = ? LIMIT 1",
                (parent["product_instance_id"],),
            ).fetchone()
            if not switched:
                raise ValueError("父件尚未完成主条码切换，不能绑定子物料")
        required_project_id = int(payload.get("child_project_id") or 0)
        if required_project_id and int(child["project_id"]) != required_project_id:
            raise ValueError("子物料项目不符合配置")
        required_type = str(payload.get("child_material_type", "")).strip()
        if required_type and child["product_type"] != required_type:
            raise ValueError("子物料类型不符合配置")
        for station_id in int_list(payload.get("required_station_ids")):
            if not completion_exists(
                conn,
                child["product_instance_id"],
                station_id,
                child["current_barcode"],
            ):
                station = conn.execute(
                    "SELECT name FROM stations WHERE id = ?",
                    (station_id,),
                ).fetchone()
                raise ValueError(
                    f"B物料未完成要求工位"
                    f"{'：' + station['name'] if station else ''}，不能绑定"
                )
        existing = conn.execute(
            """
            SELECT * FROM material_bindings
            WHERE child_product_instance_id = ? AND is_active = ?
            LIMIT 1
            """,
            (child["product_instance_id"], True),
        ).fetchone()
        if existing:
            if int(existing["parent_product_instance_id"]) != int(
                parent["product_instance_id"]
            ):
                raise ValueError("该子物料已绑定到其他产品")
            if not as_bool(payload.get("allow_duplicate"), False):
                raise ValueError("该子物料已绑定到当前产品")
            return {"ok": True, "binding_id": existing["id"], "message": "绑定关系已存在"}
        cursor = conn.execute(
            """
            INSERT INTO material_bindings
            (parent_product_instance_id, child_product_instance_id,
             parent_barcode, child_barcode, binding_type, project_id,
             station_id, step_id, operator, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parent["product_instance_id"],
                child["product_instance_id"],
                parent_barcode,
                child_barcode,
                payload.get("binding_type", required_type),
                int(payload.get("project_id") or parent["project_id"]),
                int(payload.get("station_id") or 0),
                int(payload.get("step_id") or 0) or None,
                payload.get("operator", ""),
                True,
                now_text(),
            ),
        )
        conn.execute(
            """
            UPDATE barcode_aliases
            SET barcode_type = 'child_main'
            WHERE product_instance_id = ? AND barcode = ?
            """,
            (child["product_instance_id"], child_barcode),
        )
    return {
        "ok": True,
        "binding_id": cursor.lastrowid,
        "parent_product_instance_id": parent["product_instance_id"],
        "child_product_instance_id": child["product_instance_id"],
        "message": f"B物料 {child_barcode} 已绑定到 A物料 {parent_barcode}",
    }


def unbind_material(binding_id, payload):
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        raise ValueError("解绑必须填写原因")
    with get_conn() as conn:
        binding = conn.execute(
            "SELECT * FROM material_bindings WHERE id = ?",
            (binding_id,),
        ).fetchone()
        if not binding:
            raise ValueError("绑定记录不存在")
        if not bool(binding["is_active"]):
            return {"ok": True, "message": "绑定关系已是失效状态"}
        step = (
            conn.execute(
                "SELECT bind_allow_unbind FROM steps WHERE id = ?",
                (binding["step_id"],),
            ).fetchone()
            if binding["step_id"]
            else None
        )
        if step and not bool(step["bind_allow_unbind"]):
            raise ValueError("该绑定工序未配置允许解绑")
        conn.execute(
            "UPDATE material_bindings SET is_active = ? WHERE id = ?",
            (False, binding_id),
        )
        conn.execute(
            """
            INSERT INTO maintenance_logs
            (action, message, detail, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "material-unbind",
                "管理员解绑子物料",
                json.dumps(
                    {
                        "binding_id": binding_id,
                        "parent_barcode": binding["parent_barcode"],
                        "child_barcode": binding["child_barcode"],
                        "operator": payload.get("operator", ""),
                        "reason": reason,
                    },
                    ensure_ascii=False,
                ),
                now_text(),
            ),
        )
    return {"ok": True, "message": "子物料绑定已解除"}


def trace_by_barcode(barcode):
    barcode = str(barcode or "").strip()
    if not barcode:
        raise ValueError("条码不能为空")
    with get_conn() as conn:
        alias = alias_row(conn, barcode)
        if not alias:
            return {"found": False, "barcode": barcode}
        instance_id = alias["product_instance_id"]
        aliases = conn.execute(
            """
            SELECT barcode, barcode_type, is_current, created_at, disabled_at
            FROM barcode_aliases
            WHERE product_instance_id = ?
            ORDER BY created_at, id
            """,
            (instance_id,),
        ).fetchall()
        switches = conn.execute(
            """
            SELECT * FROM barcode_switch_records
            WHERE product_instance_id = ? ORDER BY created_at, id
            """,
            (instance_id,),
        ).fetchall()
        completions = conn.execute(
            """
            SELECT station_completions.*, projects.name AS project_name,
                   stations.name AS station_name
            FROM station_completions
            JOIN projects ON projects.id = station_completions.project_id
            JOIN stations ON stations.id = station_completions.station_id
            WHERE station_completions.product_instance_id = ?
               OR (station_completions.product_instance_id IS NULL
                   AND station_completions.barcode = ?)
            ORDER BY station_completions.completed_at
            """,
            (instance_id, barcode),
        ).fetchall()
        children = conn.execute(
            """
            SELECT material_bindings.*, product_instances.current_barcode AS current_child_barcode,
                   product_instances.product_type AS child_product_type
            FROM material_bindings
            JOIN product_instances
              ON product_instances.id = material_bindings.child_product_instance_id
            WHERE material_bindings.parent_product_instance_id = ?
            ORDER BY material_bindings.created_at
            """,
            (instance_id,),
        ).fetchall()
        parents = conn.execute(
            """
            SELECT material_bindings.*, product_instances.current_barcode AS current_parent_barcode,
                   product_instances.product_type AS parent_product_type
            FROM material_bindings
            JOIN product_instances
              ON product_instances.id = material_bindings.parent_product_instance_id
            WHERE material_bindings.child_product_instance_id = ?
            ORDER BY material_bindings.created_at
            """,
            (instance_id,),
        ).fetchall()
        return {
            "found": True,
            "query_barcode": barcode,
            "product": row_to_dict(instance_row(conn, instance_id)),
            "aliases": [row_to_dict(row) for row in aliases],
            "switch_records": [row_to_dict(row) for row in switches],
            "station_completions": [row_to_dict(row) for row in completions],
            "children": [row_to_dict(row) for row in children],
            "parents": [row_to_dict(row) for row in parents],
        }
