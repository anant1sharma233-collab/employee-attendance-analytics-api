# Employee Attendance & Analytics API

A REST API built with **Python, FastAPI, and MongoDB** to manage employee records, track daily attendance, calculate working hours, regularize attendance, and generate attendance analytics.

This project was developed as part of the **HROne Software Engineer hiring assignment**. The main application code is maintained in `app/main.py`, as required by the assignment.

## Features

### 1. Employee Management

- Create employee records with input validation.
- List employees with supported filtering and pagination.
- Prevent duplicate employee codes using a unique MongoDB index.
- Return appropriate HTTP errors for invalid requests and duplicate records.

### 2. Attendance Management

- Record employee punch-ins with attendance statuses such as `PRESENT`, `WFH`, and `ON_DUTY`.
- Record punch-outs and calculate derived attendance fields.
- Calculate late minutes, work hours, overtime, and half-day status according to the implemented business rules.
- Support overnight attendance calculations.
- Regularize attendance records and maintain an audit history of changes.
- Prevent duplicate attendance records for the same employee and date using a unique compound index.

### 3. Attendance Analytics

- Generate monthly attendance summaries for individual employees.
- Generate department-level attendance summaries.
- Rank employees by late minutes, including ranking ties.
- Generate daily department attendance trends.
- Include dates without attendance records in department trends and calculate a seven-day moving average.

### 4. Database Performance

- Create configured MongoDB indexes during application startup.
- Use MongoDB aggregation pipelines for analytics.
- Provide an explain endpoint for inspecting MongoDB query execution statistics.
- Use database-level constraints and atomic update operations for important attendance operations.

### 5. Health Check

- Check whether MongoDB is responding.
- Return HTTP `200` when the database is available.
- Return HTTP `503` when the database is unavailable.

## Technology Stack

- **Language:** Python 3.11+
- **API framework:** FastAPI
- **Database:** MongoDB
- **Database driver:** PyMongo
- **Data validation:** Pydantic
- **ASGI server:** Uvicorn
- **Environment configuration:** Environment variables and `python-dotenv`

## Project Structure

```text
candidate_kit/
├── app/
│   ├── __init__.py
│   └── main.py
├── sample_data/
│   ├── attendance_logs.json
│   └── employees.json
├── .gitignore
├── DATA_MODEL.md
├── DECISIONS.md
├── openapi.yaml
├── README.md
├── requirements.txt
├── REVIEW.md
└── sample_seed.py
```

The `openapi.yaml` and `DATA_MODEL.md` files are retained from the supplied starter kit. The sample data and seed script are included to support local development and data setup where applicable.

## Prerequisites

Before running the application, make sure you have:

- Python 3.11 or later.
- A MongoDB instance, such as MongoDB Atlas or a local MongoDB server.
- Git, if you want to clone the repository.

MongoDB must be reachable when the application starts because the application creates its configured indexes during startup.

## Configuration

The application uses the following environment variables:

| Variable | Description |
|---|---|
| `MONGO_URI` | MongoDB connection URI |
| `MONGO_DB` | MongoDB database name; defaults to `attendance_db` |

For local development, create a `.env` file in the project root if your application configuration loads environment variables from it.

Example:

```env
MONGO_URI=your_mongodb_connection_uri
MONGO_DB=attendance_db
```

Replace the example URI with your actual MongoDB connection string. Never commit `.env` files, database passwords, access tokens, or other secrets to GitHub.

## Installation and Setup

### 1. Clone the repository

```powershell
git clone https://github.com/anant1sharma233-collab/employee-attendance-analytics-api.git
cd employee-attendance-analytics-api
```

### 2. Create a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can run the commands below in the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 5. Configure MongoDB

Set `MONGO_URI` and `MONGO_DB` in your environment or configure your local `.env` file as supported by the application.

Ensure that your MongoDB Atlas network access settings permit connections from your development machine. Keep database credentials private.

### 6. Start the API

From the project root, run:

```powershell
python -m uvicorn app.main:app --port 8000
```

For local development with automatic reloading:

```powershell
python -m uvicorn app.main:app --port 8000 --reload
```

## Access the API

Once the server has started, use these URLs:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json
- **Health check:** http://127.0.0.1:8000/health

Use Swagger UI to inspect endpoint parameters, request schemas, response formats, and HTTP status codes.

## API Endpoints

### Health

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check database availability |

### Employees

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees with supported filters and pagination |

### Attendance

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/attendance/punch-in` | Record an employee punch-in |
| POST | `/attendance/punch-out` | Record punch-out and calculate attendance fields |
| GET | `/attendance` | List attendance records with supported filters and pagination |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize an attendance record |

### Analytics

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/analytics/employees/{emp_code}/monthly` | Retrieve monthly employee attendance analytics |
| GET | `/analytics/departments/summary` | Retrieve department attendance summaries |
| GET | `/analytics/leaderboard/late` | Retrieve the late-comer leaderboard |
| GET | `/analytics/departments/{department}/trend` | Retrieve a department's daily attendance trend |

### Query Explain

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB execution statistics for a supported query |

Supported explain endpoint names documented for this implementation:

- `attendance_list`
- `employee_monthly`
- `department_summary`
- `late_leaderboard`
- `department_trend`

Use Swagger UI and the application's actual route definitions to confirm the exact parameters and response schemas.

## Database Indexes

The application configures the following indexes:

| Index | Purpose |
|---|---|
| `uq_employee_emp_code` | Enforces unique employee codes |
| `uq_attendance_emp_code_date` | Enforces one attendance record per employee per date |
| `ix_employee_department_code` | Supports department and employee-code access patterns |
| `ix_attendance_date_emp_code` | Supports attendance date ordering and listing |
| `ix_attendance_emp_code_date_desc` | Supports employee-specific attendance queries ordered by date |

Indexes help improve query performance and enforce important data-integrity rules. Actual performance depends on the query, data distribution, indexes, and dataset size.

## Verification

During local development, the application was started successfully and the MongoDB connection was checked using the database ping command. The health endpoint and attendance-list requests were also exercised through Swagger UI.

The observed `attendance_list` explain response reported successful execution and used the `ix_attendance_date_emp_code` index with an `IXSCAN` stage. Its winning plan did not contain a `COLLSCAN` stage.

These observations apply to the specific requests tested. They should not be interpreted as proof that every query has been benchmarked against 100,000 records or that every concurrency scenario has been independently stress-tested.

## Assignment Documentation

- **`REVIEW.md`** — Review findings, examples, fixes, and verification limitations.
- **`DECISIONS.md`** — Design decisions addressing the five assignment questions.
- **`openapi.yaml`** — API contract retained from the starter kit.
- **`DATA_MODEL.md`** — Data model documentation retained from the starter kit.

## Security and Development Notes

- Keep the main application code in `app/main.py` as required by the assignment.
- Keep MongoDB connection strings and passwords out of source control.
- Do not upload `.env`, virtual environments, or local credentials to GitHub.
- Confirm the actual implementation and API contract before relying on exact status codes, query parameters, or response fields.
- Test important business rules and concurrency scenarios against the running application before claiming they have been fully verified.

## Author

**Anant Sharma**

Project: Employee Attendance & Analytics API  
Purpose: HROne Software Engineer hiring assignment
