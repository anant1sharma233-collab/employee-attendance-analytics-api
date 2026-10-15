# Design Decisions

## 1. Which indexes did you create and why?

I created five indexes. A unique index on `employees.emp_code` prevents duplicate employees. A unique compound index on `attendance_logs.emp_code` and `date` allows only one attendance record per employee per day. The department/employee index helps filter and sort employees. The date/employee index supports attendance listing, while the employee/date index helps find an employee's attendance records. These indexes improve query performance and enforce important data rules.

## 2. What happens when simultaneous identical punch-ins arrive?

The unique compound index protects the database against duplicate attendance records. If multiple requests try to create a record for the same employee and date, only one insert can succeed. The other request receives a duplicate-key error, which the API handles as HTTP 409 Conflict. This database-level protection is safer than checking for an existing record before inserting it, because two requests could pass that check at the same time.

## 3. How are ties at the leaderboard cutoff handled?

The late leaderboard uses MongoDB ranking so employees with equal late minutes receive the same rank. For example, the ranks can be 1, 2, 2, 4. The result limit is applied after ranking, so employees tied at the cutoff are not excluded merely because of the limit. Employee code is used to order employees with equal ranking values consistently.

## 4. How does department headcount include employees without logs?

The department summary starts with employee records and joins their attendance records for the requested month. This allows eligible employees to count toward department headcount even when they have no attendance logs. Employees who have not joined by the applicable reporting cutoff are excluded. Average work hours are calculated across attendance records, rather than by averaging the averages of individual employees.

## 5. What would change for 100 times more data?

I would generate a representative larger dataset and measure query execution statistics before changing the design. I would tune indexes according to actual query patterns and review the cost of aggregation pipelines. I would also evaluate pagination, archiving old attendance records, and separating historical data if measurements showed they were needed. Any additional indexes would be tested against both read performance and write overhead.

