# Code Review — Employee Attendance & Analytics API

## 1. Purpose of This Review

The original `app/main.py` was a partially implemented FastAPI application for employee attendance management. The basic application existed, but several business rules, edge cases, database constraints, concurrency requirements, and analytics features needed attention.

I reviewed the application with a focus on correctness, data integrity, attendance calculations, input validation, concurrent requests, pagination, MongoDB aggregation, and query performance.

The examples below describe the issues addressed during implementation. The exact behavior of each item should be checked against the original starter code and the final implementation.

---

## 2. Database Health Check

**Where:** `health()` endpoint.

**Problem:**

A health endpoint should verify that MongoDB is responding. Checking only whether the FastAPI application is running is not sufficient because the application can be running while the database is unavailable.

**Example:**

If MongoDB becomes unreachable and a client calls `GET /health`, returning HTTP 200 would incorrectly suggest that database-backed operations are available.

**Fix:**

The endpoint runs a MongoDB ping. It returns HTTP 200 when the database responds and HTTP 503 when the database is unavailable.

**Why it matters:**

Monitoring systems and clients can distinguish a healthy database connection from an application that cannot access its data.

---

## 3. Duplicate Employee Codes

**Where:** Employee creation endpoint and `create_indexes()`.

**Problem:**

Employee codes are business identifiers. Two employees must not be created with the same `emp_code`.

An application-only check is not enough to guarantee uniqueness when multiple requests arrive at nearly the same time.

**Example:**

Two requests attempt to create employees with `emp_code` set to `EMP001`. Both requests could check for an existing employee before either inserts its document.

**Fix:**

A unique index on `employees.emp_code` enforces uniqueness at the database level. Duplicate-key errors are handled as HTTP 409 Conflict.

**Why it matters:**

The database remains protected even when requests overlap.

---

## 4. Duplicate Attendance Records and Punch-In Concurrency

**Where:** Punch-in endpoint and `create_indexes()`.

**Problem:**

An employee should have only one attendance record for a given date. Simultaneous punch-in requests must not create duplicate records.

**Example:**

Two requests attempt to punch in employee `EMP001` for `2026-10-15`. Both requests must not create separate attendance documents for that employee and date.

**Fix:**

A unique compound index on `attendance_logs.emp_code` and `attendance_logs.date` enforces the one-record-per-day rule. Duplicate-key errors are translated into HTTP 409 Conflict.

**Expected behavior:**

One request can create the attendance record successfully, while a competing duplicate request receives a conflict response.

**Why it matters:**

Database constraints provide reliable protection against duplicate records, including requests that arrive concurrently.

---

## 5. Late-Minute Calculation

**Where:** `compute_late_minutes()`.

**Problem:**

Late-minute calculations must follow the configured shift time, the ten-minute grace period, and the IST timezone. Overnight shifts introduce an additional edge case because the shift may start on one calendar day and continue into the next.

**Example:**

For a shift starting at 09:30, a punch-in at 09:38 is within the ten-minute grace period and should produce zero late minutes. A punch-in at 09:45 should produce 15 late minutes.

For an overnight shift, an early-morning punch-in may belong to the shift that started on the previous day.

**Fix:**

The helper was updated to account for IST, the grace period, and overnight shift boundaries.

**Why it matters:**

Late-minute totals and leaderboard results depend on consistent attendance calculations.

---

## 6. Work-Hour Calculation and Rounding

**Where:** `compute_work_hours()`.

**Problem:**

Work hours must be calculated from the actual difference between punch-in and punch-out timestamps. The final result must use the required two-decimal rounding behavior.

**Example:**

If the elapsed duration is 7 hours and 30 minutes, the result should be `7.50` hours.

Floating-point rounding can also produce unexpected results at decimal boundaries.

**Fix:**

The helper calculates elapsed seconds, converts them into hours, and uses decimal half-up rounding to two decimal places.

**Why it matters:**

Work hours are used in employee summaries, department averages, and half-day calculations.

---

## 7. Overtime and Overnight Shifts

**Where:** `compute_overtime()`.

**Problem:**

A shift that crosses midnight ends on the following calendar day. Treating its end time as belonging to the same date can calculate overtime incorrectly.

**Example:**

Consider a shift starting at 22:00 and ending at 06:00 the next day. The shift-end timestamp must be created for the next calendar day. Comparing punch-out against 06:00 on the original day would produce an incorrect result.

**Fix:**

The overtime calculation checks whether the shift end is earlier than or equal to the shift start. If so, it uses the following day for the shift-end timestamp.

The calculation also applies the configured overtime grace rule.

**Why it matters:**

Overtime should reflect the employee's actual shift rather than an incorrect calendar-day comparison.

---

## 8. Punch-Out Must Be Atomic

**Where:** `POST /attendance/punch-out`.

**Problem:**

A record that has already been punched out must not be successfully closed again. Checking the record and updating it in separate operations can allow concurrent requests to race.

**Example:**

Two requests attempt to punch out the same employee's open attendance record. Both requests should not return HTTP 200 for closing the same record.

**Fix:**

The endpoint uses a conditional atomic database update that matches a record only when it has not already been punched out.

**Expected behavior:**

Only one competing request can close the record successfully. A later request finds that the record is no longer open and receives the appropriate conflict response.

**Why it matters:**

This protects punch-out timestamps and prevents repeated recalculation of derived attendance fields.

---

## 9. Attendance Regularization and Audit History

**Where:** `PATCH /attendance/{emp_code}/{date}`.

**Problem:**

Attendance corrections must update the relevant record, recalculate derived values, and preserve an audit trail of the changes.

Concurrent corrections must not silently overwrite each other's history entries.

**Example:**

A manager corrects an employee's punch-in time. The work hours, late minutes, overtime, and half-day status must be consistent with the corrected timestamps. The correction should also be recorded in the history.

**Fix:**

The regularization endpoint validates the correction, recalculates derived attendance fields, and appends a history entry through a database update.

**Why it matters:**

The application retains a record of corrections and keeps calculated attendance fields consistent with the stored timestamps.

---

## 10. Pagination, Filtering, and Sorting

**Where:** Employee and attendance list endpoints.

**Problem:**

List endpoints must apply filters consistently, use one-based page numbers, enforce the allowed page-size limit, and calculate totals from the same filters used to retrieve the records.

**Example:**

If the client requests attendance for `EMP001` between two dates, the returned records and the total count must both reflect those filters. The total should not count unrelated employees or dates.

**Fix:**

The list endpoints apply the relevant filters, deterministic sorting, pagination, and filtered totals. Page size is restricted to the supported maximum.

**Why it matters:**

Clients receive predictable pages and accurate totals without retrieving the entire collection.

---

## 11. Employee Monthly Analytics

**Where:** `GET /analytics/employees/{emp_code}/monthly`.

**Problem:**

Monthly analytics must consider the requested employee and month and apply the attendance business rules correctly.

A calculation based on unrelated months or an incorrect attendance count can produce misleading statistics.

**Example:**

If an employee has attendance records in September and October, an October report must not include September's records.

**Fix:**

The endpoint uses a MongoDB aggregation pipeline to calculate the employee's monthly attendance statistics.

**Why it matters:**

The database performs the grouping and calculations rather than requiring the application to fetch all matching records and loop over them in Python.

---

## 12. Department Summary and Employees Without Attendance Logs

**Where:** `GET /analytics/departments/summary`.

**Problem:**

Department information belongs to employee records, while attendance data is stored in a separate collection. An aggregation that starts only from attendance logs can omit employees who have no logs.

The headcount must also respect the employee's joining date and the reporting cutoff.

**Example:**

Suppose a department has five eligible employees, but only four have attendance records for the requested month. The department headcount should still include all five eligible employees.

**Fix:**

The aggregation starts from employee records and joins attendance records for the reporting period. Employees who have not joined by the applicable cutoff are excluded.

Average work hours are calculated across attendance records rather than by taking an average of employee averages.

**Why it matters:**

The summary represents the department's eligible workforce instead of only employees who have attendance records.

---

## 13. Late Leaderboard and Ranking Ties

**Where:** `GET /analytics/leaderboard/late`.

**Problem:**

Employees with the same late-minute total must receive the same rank. Applying the result limit before ranking can also exclude employees tied at the cutoff.

**Example:**

Suppose the late-minute totals produce these ranks:

- Employee A: 60 minutes — rank 1
- Employee B: 45 minutes — rank 2
- Employee C: 45 minutes — rank 2
- Employee D: 30 minutes — rank 4

The expected ranking is `1, 2, 2, 4`, not `1, 2, 3, 4`.

**Fix:**

The leaderboard uses MongoDB ranking to assign ranks. The result limit is applied after ranking, and employee code provides deterministic ordering among tied rows.

**Why it matters:**

The leaderboard follows the required tie behavior and does not incorrectly assign different ranks to equal totals.

---

## 14. Department Trend and Missing Calendar Dates

**Where:** `GET /analytics/departments/{department}/trend`.

**Problem:**

A daily trend must return one row for every calendar date in the requested range. Days without attendance records and weekends must not disappear from the series.

The moving average must also use the appropriate preceding window.

**Example:**

If the requested range covers Monday through Sunday but no attendance records exist on Sunday, the Sunday row must still appear in the output.

**Fix:**

The endpoint uses a MongoDB aggregation pipeline to generate the date range, calculate daily attendance values, fill missing dates, and compute the seven-day moving average. The initial rows use a shorter window when fewer preceding days are available.

**Why it matters:**

The resulting series is continuous and can be used to analyze attendance trends without gaps caused by missing records.

---

## 15. MongoDB Indexes and Query Performance

**Where:** `create_indexes()` and database queries.

**Problem:**

Queries over large attendance collections can become expensive when they lack suitable indexes. Indexes must also support the application's uniqueness constraints and common filter/sort patterns.

**Fix:**

The application creates these indexes at startup:

- `uq_employee_emp_code`: enforces unique employee codes.
- `uq_attendance_emp_code_date`: enforces one attendance record per employee and date.
- `ix_employee_department_code`: supports department and employee-code access patterns.
- `ix_attendance_date_emp_code`: supports attendance date ordering and listing.
- `ix_attendance_emp_code_date_desc`: supports employee-specific attendance access ordered by date.

**Example:**

The observed explain output for `attendance_list` used `ix_attendance_date_emp_code` and showed an `IXSCAN` stage. Its winning plan did not contain `COLLSCAN`.

**Why it matters:**

Suitable indexes can reduce the number of documents examined. Their actual performance benefit must still be measured against representative datasets.

---

## 16. MongoDB Explain Endpoint

**Where:** `GET /admin/explain/{endpoint}`.

**Problem:**

It is not sufficient to assume that a query is efficient because it returns results quickly on a small sample. MongoDB execution plans provide evidence of how a query is executed.

**Fix:**

Added an admin explain endpoint for the supported names:

- `attendance_list`
- `employee_monthly`
- `department_summary`
- `late_leaderboard`
- `department_trend`

The endpoint returns MongoDB execution statistics for the query or aggregation being explained.

**Verification example:**

The `attendance_list` explain output showed:

- `executionSuccess: true`
- Index name: `ix_attendance_date_emp_code`
- Winning-plan stage: `IXSCAN`
- `totalKeysExamined: 13`
- `totalDocsExamined: 13`
- `executionTimeMillis: 1`

These values describe that particular run, not a guaranteed response time for larger datasets.

**Important requirement:**

For each supported endpoint, the explain operation must use the same relevant filters, sorting, pagination, and main query or pipeline as the real endpoint. A successful HTTP response alone does not prove this requirement.

---

## 17. Additional Endpoints Implemented

In addition to reviewing and correcting existing functionality, the application includes endpoints that were required but missing from the starter.

### Punch-Out

`POST /attendance/punch-out` closes an open attendance record and calculates work hours, overtime, and half-day status.

### Attendance Regularization

`PATCH /attendance/{emp_code}/{date}` lets an authorized business workflow correct attendance data while maintaining change history.

### Employee Monthly Analytics

`GET /analytics/employees/{emp_code}/monthly` calculates monthly attendance statistics for an employee.

### Department Summary

`GET /analytics/departments/summary` combines employee and attendance information to calculate department-level statistics.

### Late Leaderboard

`GET /analytics/leaderboard/late` ranks employees by their late minutes and handles ties.

### Department Trend

`GET /analytics/departments/{department}/trend` returns a daily attendance series with missing dates filled and a seven-day moving average.

### Admin Explain

`GET /admin/explain/{endpoint}` exposes MongoDB execution statistics for the supported endpoint queries or pipelines.

---

## 18. Items Examined and Design Decisions

### Database uniqueness

A unique index is necessary for enforcing employee-code and employee/date uniqueness. An application-only existence check cannot guarantee uniqueness when requests run concurrently.

### Atomic updates

A conditional atomic database update is appropriate for punch-out because a separate read followed by an update can allow competing requests to act on the same open record.

### Audit history

Regularization history should be appended atomically so that concurrent corrections do not silently lose earlier history entries.

### Aggregation in MongoDB

Analytics are implemented using MongoDB aggregation pipelines to perform grouping, joining, ranking, date generation, and moving-average calculations in the database.

### Index creation at startup

Indexes are created through the application startup routine so that a clean application startup does not depend on a developer manually creating the indexes first.

These are design choices, not separate defects in themselves.

---

## 19. Verification Performed and Limitations

The application was started locally, Swagger UI was opened, and database-backed endpoints were exercised.

The following checks were observed during development:

- The health endpoint returned a successful response while MongoDB was reachable.
- The attendance list endpoint returned HTTP 200.
- The supported explain endpoint names were exercised.
- The observed `attendance_list` execution plan used `ix_attendance_date_emp_code` with `IXSCAN` and no `COLLSCAN` in its winning plan.

These checks demonstrate the behavior observed during those runs.

They do not, by themselves, prove that every business-rule edge case, every simultaneous-request scenario, or the full 100,000-record performance requirement has passed. Those require dedicated tests with representative data.

