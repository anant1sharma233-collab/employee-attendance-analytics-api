# Employee Attendance & Analytics API

A REST API built with **FastAPI, Python, and MongoDB** for managing employee attendance, calculating work hours, regularizing attendance records, and generating attendance analytics.

This project was developed as part of the HROne Software Engineer hiring assignment. The application code is maintained in `app/main.py`, as required by the assignment.

## Features

### 1. Employee Management
- Create employee records.
- List employees with department filtering and pagination.
- Prevent duplicate employee codes using a unique database index.

### 2. Attendance Management
- Record employee punch-ins.
- Record punch-outs and calculate derived attendance fields.
- Calculate work hours, late minutes, overtime, and half-day status.
- Regularize attendance records and maintain a change history.
- Prevent duplicate attendance records for the same employee and date.

### 3. Attendance Analytics
- Generate monthly attendance summaries for individual employees.
- Generate department-level attendance summaries.
- Rank employees by late minutes, including ranking ties.
- Generate daily department attendance trends.
- Include dates without attendance records in the trend and calculate a seven-day moving average.

### 4. Database Performance
- Create database indexes automatically at application startup.
- Use MongoDB aggregation pipelines for analytics.
- Provide an explain endpoint for inspecting MongoDB query execution statistics.

### 5. Health Check
- Check whether MongoDB is responding.
- Return HTTP 200 when the database is available and HTTP 503 when it is unavailable.

## Technology Stack

- **Language:** Python 3.11+
- **API Framework:** FastAPI
- **Database:** MongoDB
- **Database Driver:** PyMongo
- **Data Validation:** Pydantic
- **ASGI Server:** Uvicorn
- **Environment Configuration:** Environment variables and `python-dotenv`

## Project Structure

candidate_kit/
├── app/
│   └── main.py
├── requirements.txt
├── README.md
├── REVIEW.md
├── DECISIONS.md
├── .gitignore
├── openapi.yaml
└── DATA_MODEL.md

The `openapi.yaml` and `DATA_MODEL.md` files are included if retained from the supplied starter kit.

## Prerequisites

Before running the application, install:

- Python 3.11 or later.
- A MongoDB instance, such as MongoDB Atlas or a local MongoDB server.
- Git, if you want to clone the repository.

MongoDB must be reachable when the application starts because the application creates its indexes during startup.

## Configuration

The application reads these environment variables:

| Variable | Description |
|---|---|
| `MONGO_URI` | MongoDB connection URI |
| `MONGO_DB` | Database name; defaults to `attendance_db` |

Set these variables in your environment before starting the application.

For local development, a `.env` file can be used if supported by the application's configuration:

```env
MONGO_URI=your_mongodb_connection_uri
MONGO_DB=attendance_db
```

**Security:** Replace the example URI with your own connection string. Never commit `.env`, database passwords, or other credentials to GitHub.

## Installation

### 1. Clone the repository


### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the virtual environment

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure MongoDB

Set `MONGO_URI` and `MONGO_DB` in your environment. Confirm that the database is accessible from your machine.

## Run the Application

From the project root, execute:

```bash
uvicorn app.main:app --port 8000
```

The API will be available at:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json
- **Health check:** http://127.0.0.1:8000/health

The application creates its configured indexes during startup.

## API Endpoints

### Health

- `GET /health` — Check database availability.

### Employees

- `POST /employees` — Create an employee.
- `GET /employees` — List employees with supported filtering and pagination.

### Attendance

- `POST /attendance/punch-in` — Record a punch-in.
- `POST /attendance/punch-out` — Record a punch-out and calculate derived attendance fields.
- `GET /attendance` — List attendance records with supported filters and pagination.
- `PATCH /attendance/{emp_code}/{date}` — Regularize an attendance record.

### Analytics

- `GET /analytics/employees/{emp_code}/monthly` — Retrieve monthly analytics for an employee.
- `GET /analytics/departments/summary` — Retrieve a department attendance summary.
- `GET /analytics/leaderboard/late` — Retrieve the late-comer leaderboard.
- `GET /analytics/departments/{department}/trend` — Retrieve a department's daily attendance trend.

### Query Explain

- `GET /admin/explain/{endpoint}` — Inspect MongoDB execution statistics for a supported endpoint.

Supported explain endpoint names:

- `attendance_list`
- `employee_monthly`
- `department_summary`
- `late_leaderboard`
- `department_trend`

Refer to Swagger UI and `openapi.yaml` for the exact request parameters, schemas, and response formats.

## Database Indexes

The application creates the following indexes:

- `uq_employee_emp_code` — Enforces unique employee codes.
- `uq_attendance_emp_code_date` — Enforces one attendance record per employee per date.
- `ix_employee_department_code` — Supports department and employee-code access patterns.
- `ix_attendance_date_emp_code` — Supports attendance date ordering and listing.
- `ix_attendance_emp_code_date_desc` — Supports employee-specific attendance queries ordered by date.

These indexes support data integrity and common query patterns. Actual performance depends on query shape, data distribution, and dataset size.

## Verification

During development, the application was started locally and endpoints were exercised through Swagger UI.

The observed `attendance_list` explain output reported successful execution and used the `ix_attendance_date_emp_code` index with an `IXSCAN` stage. Its winning plan did not contain a `COLLSCAN` stage.

This is evidence for that specific query execution, not a claim that every query has been benchmarked against 100,000 records or that every concurrency scenario has been independently stress-tested.

## Assignment Documentation

- **`REVIEW.md`** — Review findings, examples, fixes, and verification limitations.
- **`DECISIONS.md`** — Answers to the five design questions in the assignment.
- **`openapi.yaml`** — API contract supplied with the starter kit, if retained.
- **`DATA_MODEL.md`** — Data model documentation supplied with the starter kit, if retained.

## Notes

- Keep application code in `app/main.py` as required by the assignment.
- Ensure the application can connect to MongoDB before startup.
- Do not commit virtual environments, `.env` files, credentials, or other secrets.
- Use the provided API contract to verify exact status codes, parameters, and response fields.
