
"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi.responses import Response
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient
from typing import Optional, Literal
from pydantic import BaseModel, Field
from decimal import Decimal, ROUND_HALF_UP
from pymongo import MongoClient, ReturnDocument
from bson import json_util

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

def create_indexes():
    # Employee codes must be unique.
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employee_emp_code",
    )

    # One attendance record per employee per attendance date.
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_code_date",
    )

    # Employee listing and attendance filtering.
    db.employees.create_index(
        [("department", 1), ("emp_code", 1)],
        name="ix_employee_department_code",
    )

    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="ix_attendance_date_emp_code",
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", -1)],
        name="ix_attendance_emp_code_date_desc",
    )

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def initialize_database_indexes():
    create_indexes()



# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    shift_end: str = "18:30",
) -> int:
    punch_in = punch_in.astimezone(IST).replace(microsecond=0)

    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    start_time = punch_in.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )

    # For overnight shifts, an early-morning punch-in
    # belongs to the shift that started the previous day.
    if end_hour * 60 + end_minute <= start_hour * 60 + start_minute:
        if punch_in.hour * 60 + punch_in.minute < end_hour * 60 + end_minute:
            start_time -= timedelta(days=1)

    late_seconds = (punch_in - start_time).total_seconds()

    if late_seconds <= 10 * 60:
        return 0

    return int(late_seconds // 60)

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = (punch_out - punch_in).total_seconds()
    hours = Decimal(str(seconds / 3600))
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str,
) -> int:
    attendance_date = datetime.fromisoformat(date_str).date()

    start_time = datetime.strptime(shift_start, "%H:%M").time()
    end_time = datetime.strptime(shift_end, "%H:%M").time()

    end_date = attendance_date
    if end_time <= start_time:
        end_date += timedelta(days=1)

    shift_end_dt = datetime.combine(
        end_date,
        end_time,
        tzinfo=IST,
    )

    punch_out = punch_out.astimezone(IST).replace(microsecond=0)
    overtime_seconds = (punch_out - shift_end_dt).total_seconds()

    if overtime_seconds < 30 * 60:
        return 0

    return int(overtime_seconds // 60)

def epoch_ms(value):
    """Convert a MongoDB datetime to epoch milliseconds."""
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return int(value.timestamp() * 1000)

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )


class RegularizeRequest(BaseModel):
    status: Optional[
        Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]
    ] = None

    punch_in: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )

    punch_out: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )

    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")

    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except Exception as exc:
        # Duplicate-key errors will be handled properly once the
        # unique emp_code index is created.
        from pymongo.errors import DuplicateKeyError

        if isinstance(exc, DuplicateKeyError):
            raise HTTPException(409, "emp_code already exists")
        raise

    doc.pop("_id", None)
    doc["created_at"] = epoch_ms(doc["created_at"])
    return doc




@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail="page must be at least 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100",
        )

    # Apply the optional department filter.
    q = {}
    if department:
        q["department"] = department

    # Calculate pagination.
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)

    # Fetch employees sorted by employee code.
    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    # Convert created_at to epoch milliseconds.
    for item in items:
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = epoch_ms(item["created_at"])

    # Return the paginated response.
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(422, "page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(422, "page_size must be between 1 and 100")

    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        for value in (date_from, date_to):
            if value is not None:
                try:
                    parsed = datetime.strptime(value, "%Y-%m-%d")
                    if parsed.strftime("%Y-%m-%d") != value:
                        raise ValueError
                except ValueError:
                    raise HTTPException(422, "Dates must use YYYY-MM-DD")

        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from cannot be after date_to")

        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to

    if status:
        allowed = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
        if status not in allowed:
            raise HTTPException(422, "Invalid attendance status")
        q["status"] = status

    skip = (page - 1) * page_size
    total = db.attendance_logs.count_documents(q)

    items = list(
        db.attendance_logs.find(q, {"_id": 0, "history._id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    for item in items:
        item["punch_in"] = epoch_ms(item.get("punch_in"))
        item["punch_out"] = epoch_ms(item.get("punch_out"))

        for entry in item.get("history", []):
            if isinstance(entry.get("at"), datetime):
                entry["at"] = epoch_ms(entry["at"])

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    from pymongo.errors import DuplicateKeyError

    # Confirm that the employee exists.
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # Use the supplied epoch-millisecond timestamp or current IST time.
    if body.punched_at is not None:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=IST,
        )
    else:
        ts = datetime.now(IST)

    # Truncate to whole seconds and determine the IST attendance date.
    ts = ts.replace(microsecond=0)
    attendance_date = ts.date().isoformat()

    # Build the record. The unique (emp_code, date) index is the
    # final protection against simultaneous duplicate punch-ins.
    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts,
            emp["shift_start"],
            emp["shift_end"],
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this date",
        )

    # Never expose MongoDB's internal ID.
    doc.pop("_id", None)
    doc.pop("id", None)

    doc["punch_in"] = epoch_ms(doc["punch_in"])
    doc["punch_out"] = epoch_ms(doc["punch_out"])

    return doc


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    # Check whether the employee exists.
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # Get punch-out time and normalize it to naive UTC for MongoDB.
    if body.punched_at is None:
        ts_utc = datetime.now(timezone.utc).replace(
            microsecond=0
        ).replace(tzinfo=None)
    else:
        ts_utc = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc,
        ).replace(microsecond=0, tzinfo=None)

    # Find the most recent open punch-in that occurred by punch-out time.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {
                "$ne": None,
                "$lte": ts_utc,
            },
            "punch_out": None,
        },
        sort=[("punch_in", -1)],
    )

    if record is None:
        previous = db.attendance_logs.find_one(
            {
                "emp_code": body.emp_code,
                "punch_in": {"$ne": None, "$lte": ts_utc},
            },
            sort=[("punch_in", -1)],
        )

        if previous is not None and previous.get("punch_out") is not None:
            raise HTTPException(
                status_code=409,
                detail="Already punched out",
            )

        raise HTTPException(
            status_code=404,
            detail="No open punch-in found",
        )

    # PyMongo normally returns naive UTC datetimes.
    punch_in_utc = record["punch_in"].replace(
        tzinfo=timezone.utc
    )

    punch_out_aware = ts_utc.replace(tzinfo=timezone.utc)

    elapsed_seconds = (
        punch_out_aware - punch_in_utc
    ).total_seconds()

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours",
        )

    # Calculate work hours using half-up rounding.
    work_hours = float(
        Decimal(str(elapsed_seconds / 3600)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )

    # Convert punch-out time to IST for shift calculations.
    punch_out_ist = punch_out_aware.astimezone(IST)

    overtime_minutes = compute_overtime(
        punch_out_ist,
        emp["shift_start"],
        emp["shift_end"],
        record["date"],
    )

    half_day = work_hours < 4.50

    # Atomically update the record to prevent double punch-out.
    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts_utc,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out",
        )

    # Return API timestamps as epoch milliseconds.
    updated.pop("_id", None)
    updated.pop("id", None)
    updated["punch_in"] = epoch_ms(updated.get("punch_in"))
    updated["punch_out"] = epoch_ms(updated.get("punch_out"))

    for entry in updated.get("history", []):
        if isinstance(entry.get("at"), datetime):
            entry["at"] = epoch_ms(entry["at"])

    return updated


#   PATCH /attendance/{emp_code}/{date}

@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeRequest,
):
    # Validate the attendance date.
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        if parsed_date.isoformat() != date:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date; use YYYY-MM-DD")

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": date}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    # Distinguish an omitted field from a field explicitly sent as null.
    supplied = body.model_fields_set

    old_status = record["status"]
    old_in = record.get("punch_in")
    old_out = record.get("punch_out")

    new_status = body.status if "status" in supplied else old_status
    new_in = old_in
    new_out = old_out

    if "punch_in" in supplied:
        new_in = (
            datetime.fromtimestamp(body.punch_in / 1000, timezone.utc)
            .replace(microsecond=0, tzinfo=None)
            if body.punch_in is not None else None
        )

    if "punch_out" in supplied:
        new_out = (
            datetime.fromtimestamp(body.punch_out / 1000, timezone.utc)
            .replace(microsecond=0, tzinfo=None)
            if body.punch_out is not None else None
        )

    if new_status in ("ABSENT", "LEAVE"):
        if "punch_in" in supplied or "punch_out" in supplied:
            raise HTTPException(
                status_code=422,
                detail="Do not supply punch times for ABSENT or LEAVE",
            )
        new_in = None
        new_out = None
    elif new_in is None:
        raise HTTPException(
            status_code=422,
            detail="Presence status requires punch_in",
        )

    # R1: punch-in must belong to this attendance date in IST.
    if new_in is not None:
        local_in = new_in.replace(tzinfo=timezone.utc).astimezone(IST)
        if local_in.date().isoformat() != date:
            raise HTTPException(
                status_code=422,
                detail="punch_in must fall on the attendance date in IST",
            )

    # R3-R5: validate punch-out and recompute derived values.
    if new_out is not None:
        if new_in is None:
            raise HTTPException(status_code=422, detail="punch_out requires punch_in")

        elapsed = (new_out - new_in).total_seconds()
        if elapsed <= 0 or elapsed > 24 * 60 * 60:
            raise HTTPException(
                status_code=422,
                detail="punch_out must be after punch_in and within 24 hours",
            )

    if new_in is not None:
        local_in = new_in.replace(tzinfo=timezone.utc).astimezone(IST)
        late_minutes = compute_late_minutes(local_in, emp["shift_start"], emp["shift_end"])
    else:
        late_minutes = 0

    if new_in is not None and new_out is not None:
        elapsed = (new_out - new_in).total_seconds()
        work_hours = float(
            Decimal(str(elapsed / 3600)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        overtime_minutes = compute_overtime(
            new_out.replace(tzinfo=timezone.utc),
            emp["shift_start"],
            emp["shift_end"],
            date,
        )
        half_day = work_hours < 4.50
    else:
        work_hours = None
        overtime_minutes = 0
        half_day = False

    # Convert stored UTC datetimes to epoch milliseconds for the API/history.
    def epoch_ms(value):
        if value is None:
            return None
        return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)

    new_values = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
        "late_minutes": late_minutes,
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    old_values = {
        "status": old_status,
        "punch_in": old_in,
        "punch_out": old_out,
        "late_minutes": record.get("late_minutes", 0),
        "work_hours": record.get("work_hours"),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False),
    }

    changes = {}
    for key, new_value in new_values.items():
        old_value = old_values[key]
        if key in ("punch_in", "punch_out"):
            old_compare = epoch_ms(old_value)
            new_compare = epoch_ms(new_value)
        else:
            old_compare = old_value
            new_compare = new_value

        if old_compare != new_compare:
            changes[key] = {
                "from": old_compare,
                "to": new_compare,
            }

    if not changes:
        raise HTTPException(status_code=422, detail="Request changes nothing")

    history_entry = {
        "at": int(datetime.now(timezone.utc).timestamp() * 1000),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    # Compare-and-set: don't silently overwrite another correction.
    history = record.get("history", [])
    query = {"_id": record["_id"]}
    if "history" in record:
        query["history"] = history
    else:
        query["history"] = {"$exists": False}

    set_values = {
        key: value
        for key, value in new_values.items()
    }

    updated = db.attendance_logs.find_one_and_update(
        query,
        {
            "$set": set_values,
            "$push": {"history": history_entry},
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Record changed concurrently; retry the correction",
        )

    updated["punch_in"] = epoch_ms(updated.get("punch_in"))
    updated["punch_out"] = epoch_ms(updated.get("punch_out"))
    updated["history"] = [
        {
            **entry,
            "at": epoch_ms(entry["at"])
            if isinstance(entry.get("at"), datetime)
            else entry.get("at"),
        }
        for entry in updated.get("history", [])
    ]

    updated.pop("_id", None)
    updated.pop("id", None)

    return updated

#   GET   /analytics/employees/{emp_code}/monthly



# GET   /analytics/employees/{emp_code}/monthly

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    month: str,
):
    # Validate month format.
    try:
        month_date = datetime.strptime(month, "%Y-%m")
        if month_date.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM",
        )

    # Check that the employee exists.
    employee = db.employees.find_one({"emp_code": emp_code})
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # Calculate the month boundaries.
    start_date = month + "-01"

    if month_date.month == 12:
        next_month = datetime(month_date.year + 1, 1, 1)
    else:
        next_month = datetime(
            month_date.year,
            month_date.month + 1,
            1,
        )

    end_date = next_month.strftime("%Y-%m-%d")

    # Count weekdays (Monday-Friday) in the selected month.
    working_days = 0
    current_day = month_date.date()

    while current_day < next_month.date():
        if current_day.weekday() < 5:
            working_days += 1
        current_day += timedelta(days=1)

    # Aggregate attendance in MongoDB.
    pipeline = _employee_monthly_pipeline(emp_code, start_date, end_date)

    results = list(db.attendance_logs.aggregate(pipeline))

    if results:
        stats = results[0]
    else:
        stats = {
            "present_days": 0,
            "leave_days": 0,
            "late_count": 0,
            "total_late_minutes": 0,
            "total_overtime_minutes": 0,
        }

    present_days = stats["present_days"]

    if working_days > 0:
        attendance_pct = float(
            (Decimal(str(present_days)) * Decimal("100")
             / Decimal(working_days)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        )
    else:
        attendance_pct = None

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats["leave_days"],
        "late_count": stats["late_count"],
        "total_late_minutes": stats["total_late_minutes"],
        "total_overtime_minutes": stats["total_overtime_minutes"],
        "attendance_pct": attendance_pct,
    }

@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: Optional[str] = None,
):
    # Validate YYYY-MM
    try:
        month_date = datetime.strptime(month, "%Y-%m")
        if month_date.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM",
        )

    start_date = month + "-01"

    if month_date.month == 12:
        end_date = f"{month_date.year + 1:04d}-01-01"
    else:
        end_date = (
            f"{month_date.year:04d}-"
            f"{month_date.month + 1:02d}-01"
        )

    # Start from employees so employees with zero logs count.
    employee_match = {}
    if department:
        employee_match["department"] = department

    pipeline = _department_summary_pipeline(employee_match, start_date, end_date)

    items = list(db.employees.aggregate(pipeline))

    # Apply required half-up rounding to average work hours.
    for item in items:
        if item["avg_work_hours"] is not None:
            item["avg_work_hours"] = float(
                Decimal(str(item["avg_work_hours"])).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            )

    return {
        "month": month,
        "items": items,
    }



#   GET   /analytics/leaderboard/late


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None,
):
    # Validate the month.
    try:
        month_date = datetime.strptime(month, "%Y-%m")
        if month_date.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM",
        )

    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 50",
        )

    # Calculate the first day of the next month.
    start_date = month + "-01"

    if month_date.month == 12:
        next_month = f"{month_date.year + 1:04d}-01-01"
    else:
        next_month = (
            f"{month_date.year:04d}-{month_date.month + 1:02d}-01"
        )

    # Group monthly attendance by employee.
    pipeline = _late_leaderboard_pipeline(start_date, next_month, department, limit)

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items,
    }

#   GET   /analytics/departments/{department}/trend

@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    # Validate dates and the maximum inclusive range.
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
        end = datetime.strptime(to_date, "%Y-%m-%d").date()

        if start.isoformat() != from_date or end.isoformat() != to_date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD format",
        )

    if end < start:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'",
        )

    day_count = (end - start).days + 1

    if day_count > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days",
        )

    # A department must exist even if it has no attendance records.
    if not db.employees.find_one({"department": department}):
        raise HTTPException(
            status_code=404,
            detail="Department not found",
        )

    # Generate every calendar day inside MongoDB, not in Python.
    pipeline = _department_trend_pipeline(department, from_date, day_count)

    items = list(db.employees.aggregate(pipeline))

    # Use Decimal half-up rounding for the final numeric outputs.
    def round_half_up(value, places=4):
        if value is None:
            return None

        return float(
            Decimal(str(value)).quantize(
                Decimal("0." + "0" * (places - 1) + "1"),
                rounding=ROUND_HALF_UP,
            )
        )

    for item in items:
        item["attendance_rate"] = round_half_up(
            item["attendance_rate"]
        )
        item["moving_avg_7d"] = round_half_up(
            item["moving_avg_7d"]
        )

    return {
        "department": department,
        "items": items,
    }
#   GET   /admin/explain/{endpoint}



def _employee_monthly_pipeline(emp_code, start_date, end_date):
    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": start_date,
                    "$lt": end_date,
                },
            }
        },
        {
            "$set": {
                "weekday": {
                    "$dayOfWeek": {
                        "$dateFromString": {
                            "dateString": "$date",
                            "format": "%Y-%m-%d",
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {"$gte": ["$weekday", 2]},
                                    {"$lte": ["$weekday", 6]},
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                },
            }
        },
    ]
    return pipeline

def _department_summary_pipeline(employee_match, start_date, end_date):
    pipeline = [
        {"$match": employee_match},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$gte": ["$date", start_date]},
                                    {"$lt": ["$date", end_date]},
                                ]
                            }
                        }
                    },
                    {
                        "$set": {
                            "weekday": {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date"
                                    }
                                }
                            }
                        }
                    },
                ],
                "as": "logs",
            }
        },
        {
            "$set": {
                "eligible": {
                    "$lt": ["$joined_on", end_date]
                }
            }
        },
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": "$department",
                "headcount_codes": {
                    "$addToSet": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$emp_code", None]},
                                   {"$lt": ["$joined_on", end_date]},
                                ]
                            },
                            "$emp_code",
                            None,
                        ]
                    }
                },
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {"$gte": ["$logs.weekday", 2]},
                                    {"$lte": ["$logs.weekday", 6]},
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "work_hours_values": {
                    "$push": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {"$ne": ["$logs.work_hours", None]},
                                ]
                            },
                            "$logs.work_hours",
                            None,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$logs.late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
    "$sum": {
        "$cond": [
            {"$gt": ["$logs.late_minutes", 0]},
            "$logs.late_minutes",
            0,
        ]
    }
    },
                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$set": {
                "headcount": {
                    "$size": {
                        "$filter": {
                            "input": "$headcount_codes",
                            "as": "code",
                            "cond": {"$ne": ["$$code", None]},
                        }
                    }
                },
                "avg_work_hours": {
                    "$avg": {
                        "$filter": {
                            "input": "$work_hours_values",
                            "as": "hours",
                            "cond": {"$ne": ["$$hours", None]},
                        }
                    }
                },
            }
        },
        {"$match": {"headcount": {"$gt": 0}}},
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "avg_work_hours": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },
        {"$sort": {"department": 1}},
    ]
    return pipeline

def _late_leaderboard_pipeline(start_date, next_month, department, limit):
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": start_date,
                    "$lt": next_month,
                }
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    # Apply the department filter before ranking.
    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    # $rank gives equal totals the same rank and skips the next rank.
    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                },
            }
        },
        # Apply the limit after ranking, preserving ties.
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
                "rank": 1,
            }
        },
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
    ])
    return pipeline

def _department_trend_pipeline(department, from_date, day_count):
    pipeline = [
        {"$match": {"department": department}},
        {"$limit": 1},
        {
            "$project": {
                "_id": 0,
                "days": {
                    "$range": [0, day_count]
                },
                "start_date": {
                    "$dateFromString": {
                        "dateString": from_date,
                        "format": "%Y-%m-%d",
                    }
                },
            }
        },
        {"$unwind": "$days"},
        {
            "$project": {
                "_id": 0,
                "date_obj": {
                    "$dateAdd": {
                        "startDate": "$start_date",
                        "unit": "day",
                        "amount": "$days",
                    }
                },
            }
        },
        {
            "$set": {
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$date_obj",
                    }
                },
                "is_working_day": {
                    "$lte": [
                        {
                            "$isoDayOfWeek": "$date_obj"
                        },
                        5,
                    ]
                },
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$department",
                                            department,
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            "$joined_on",
                                            "$$day",
                                        ]
                                    },
                                ]
                            }
                        }
                    },
                    {"$count": "count"},
                ],
                "as": "headcount_data",
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$headcount_data.count",
                                0,
                            ]
                        },
                        0,
                    ]
                }
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"day": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": ["$date", "$$day"]
                            }
                        }
                    },
                    {
                        "$lookup": {
                            "from": "employees",
                            "localField": "emp_code",
                            "foreignField": "emp_code",
                            "as": "employee",
                        }
                    },
                    {"$unwind": "$employee"},
                    {
                        "$match": {
                            "employee.department": department
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                [
                                                    "PRESENT",
                                                    "WFH",
                                                    "ON_DUTY",
                                                ],
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                "$half_day",
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                "$late_minutes",
                                                0,
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "attendance_data",
            }
        },
        {
            "$set": {
                "present_count": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$attendance_data.present_count",
                                0,
                            ]
                        },
                        0,
                    ]
                },
                "late_count": {
                    "$ifNull": [
                        {
                            "$arrayElemAt": [
                                "$attendance_data.late_count",
                                0,
                            ]
                        },
                        0,
                    ]
                },
            }
        },
   
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$round": [
                                {
                                    "$divide": [
                                        "$present_count",
                                        "$headcount",
                                    ]
                                },
                                4,
                            ]
                        },
                        None,
                    ]
                }
            }
        },

        {
            "$setWindowFields": {
                "sortBy": {"date_obj": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, 0]
                        },
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
        {"$sort": {"date": 1}},
    ]
    return pipeline

@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    month: Optional[str] = None,
    department: Optional[str] = None,
    emp_code: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    limit: int = 10,
):
    allowed = {"attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"}
    if endpoint not in allowed:
        raise HTTPException(422, "Unsupported endpoint name")

    collection = "attendance_logs"
    if endpoint == "attendance_list":
        if page < 1 or not 1 <= page_size <= 100:
            raise HTTPException(422, "Invalid pagination")
        query = {}
        if emp_code:
            query["emp_code"] = emp_code
        if status:
            if status not in {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}:
                raise HTTPException(422, "Invalid attendance status")
            query["status"] = status
        for d in (date_from, date_to):
            if d:
                try:
                    if datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d") != d:
                        raise ValueError
                except ValueError:
                    raise HTTPException(422, "Dates must use YYYY-MM-DD")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from cannot be after date_to")
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        command = {
            "find": "attendance_logs", "filter": query,
            "sort": {"date": -1, "emp_code": 1},
            "skip": (page - 1) * page_size, "limit": page_size,
            "projection": {"_id": 0, "history._id": 0},
        }
    elif endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(422, "department, from and to are required")
        try:
            start = datetime.strptime(from_date, "%Y-%m-%d").date()
            end = datetime.strptime(to_date, "%Y-%m-%d").date()
            if start.isoformat() != from_date or end.isoformat() != to_date:
                raise ValueError
        except ValueError:
            raise HTTPException(422, "Dates must use YYYY-MM-DD")
        day_count = (end - start).days + 1
        if not 1 <= day_count <= 92:
            raise HTTPException(422, "Invalid date range")
        if not db.employees.find_one({"department": department}):
            raise HTTPException(404, "Department not found")
        collection = "employees"
        pipeline = _department_trend_pipeline(department, from_date, day_count)
        command = {"aggregate": collection, "pipeline": pipeline, "cursor": {}}
    else:
        if not month:
            raise HTTPException(422, "month is required")
        try:
            month_date = datetime.strptime(month, "%Y-%m")
            if month_date.strftime("%Y-%m") != month:
                raise ValueError
        except ValueError:
            raise HTTPException(422, "month must use YYYY-MM")
        start_date = month + "-01"
        if month_date.month == 12:
            end_date = f"{month_date.year + 1:04d}-01-01"
        else:
            end_date = f"{month_date.year:04d}-{month_date.month + 1:02d}-01"
        if endpoint == "employee_monthly":
            if not emp_code:
                raise HTTPException(422, "emp_code is required")
            pipeline = _employee_monthly_pipeline(emp_code, start_date, end_date)
        elif endpoint == "department_summary":
            collection = "employees"
            pipeline = _department_summary_pipeline(
                {"department": department} if department else {}, start_date, end_date
            )
        else:
            if not 1 <= limit <= 50:
                raise HTTPException(422, "limit must be between 1 and 50")
            pipeline = _late_leaderboard_pipeline(start_date, end_date, department, limit)
        command = {"aggregate": collection, "pipeline": pipeline, "cursor": {}}

    try:
        result = db.command("explain", command, verbosity="executionStats")
    except Exception as exc:
        raise HTTPException(500, "Could not generate MongoDB execution plan") from exc
    return Response(
        content=json_util.dumps({"endpoint": endpoint, "collection": collection, "explain": result}),
        media_type="application/json",
    )
# --------------------------------------------------------------------------- #