# **MSSQL Security Configuration**

## **Creating a Restricted MSSQL User**

It’s crucial to create a dedicated MSSQL user with minimal permissions for the MCP server. **Never use the ****`sa`**** account** or a user with full administrative privileges.

### **1. Create a New MSSQL Login and User**

Run these commands as an admin in **SQL Server Management Studio (SSMS)** or via a script:

```sql
-- Create a new login at the server level
CREATE LOGIN mcp_user WITH PASSWORD = 'Your_Secure_Password';

-- Switch to your database
USE your_database;

-- Create a user inside the database linked to the login
CREATE USER mcp_user FOR LOGIN mcp_user;
```

### **2. Grant Minimal Required Permissions**

#### **Basic Read-Only Access (Recommended for Exploration & Analysis)**

```sql
-- Grant SELECT permission only
ALTER ROLE db_datareader ADD MEMBER mcp_user;
```

#### **Standard Access (Allows Data Modification but No Structural Changes)**

```sql
-- Grant read and write access, but prevent schema modifications
ALTER ROLE db_datareader ADD MEMBER mcp_user;
ALTER ROLE db_datawriter ADD MEMBER mcp_user;
```

#### **Advanced Access (Includes Temporary Table Creation for Complex Queries)**

```sql
-- Grant additional permission for temporary table creation
GRANT CREATE TABLE TO mcp_user;
GRANT CREATE PROCEDURE TO mcp_user;
```

### **3. Restrict Schema and Table Access (Optional)**

If `mcp_user` should access only specific tables, **avoid role-based permissions** and use **explicit grants**:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.specific_table TO mcp_user;
```

## **Additional Security Measures**

### **1. Restrict Network Access**

- **If the MCP server runs locally**, allow connections only from `localhost`.
- **For remote access**, configure firewalls to allow only specific IP addresses.
- **Disable ****`sa`**** login** if not required:
  ```sql
  ALTER LOGIN sa DISABLE;
  ```

### **2. Limit Query Execution & Resource Consumption**

To prevent excessive resource usage by `mcp_user`:

```sql
-- Limit queries and updates per hour
ALTER LOGIN mcp_user 
WITH 
    CHECK_POLICY = ON, 
    CHECK_EXPIRATION = ON;

-- Set resource governor limits (if applicable)
EXEC sp_configure 'user connections', 100;
```

### **3. Column-Level Security (For Sensitive Data)**

To restrict access to specific columns:

```sql
GRANT SELECT (public_column1, public_column2) 
ON dbo.sensitive_table TO mcp_user;
```

### **4. Enable Auditing and Logging**

To track user activities:

```sql
-- Enable audit logging (available in Enterprise Edition)
CREATE SERVER AUDIT MCP_Audit 
TO FILE ( FILEPATH = 'C:\SQL_Audit\' );

-- Attach to the database
CREATE DATABASE AUDIT SPECIFICATION MCP_DB_Audit
FOR SERVER AUDIT MCP_Audit
ADD (SELECT, INSERT, UPDATE, DELETE ON DATABASE::your_database BY mcp_user);

ALTER DATABASE AUDIT SPECIFICATION MCP_DB_Audit WITH (STATE = ON);
```

## **Environment Configuration**

Use the restricted credentials in your server environment:

```bash
MSSQL_USER=mcp_user
MSSQL_PASSWORD=your_secure_password
MSSQL_DATABASE=your_database
MSSQL_HOST=localhost
```

## **Monitoring Usage**

### **Check Active Connections**

```sql
SELECT session_id, login_name, status, host_name, program_name
FROM sys.dm_exec_sessions
WHERE login_name = 'mcp_user';
```

### **Review Granted Permissions**

```sql
EXEC sp_helprotect NULL, 'mcp_user';
```

### **Track Recent Queries by User**

```sql
SELECT session_id, start_time, status, command, text
FROM sys.dm_exec_requests r
JOIN sys.dm_exec_sessions s ON r.session_id = s.session_id
JOIN sys.dm_exec_sql_text(r.sql_handle) AS sql_text ON 1=1
WHERE login_name = 'mcp_user';
```

## **Best Practices**

1. **Regular Password Rotation**

   - Use strong, randomly generated passwords.
   - Change the MCP user’s password periodically.
   - Update application configurations after password changes.

2. **Review and Adjust Permissions Periodically**

   - Audit granted permissions and remove unnecessary ones.
   - Keep permissions **as restrictive as possible**.

3. **Monitor Query Patterns**

   - Set up alerts for **unusual activity**.
   - Maintain **detailed logs** of database access.

4. **Protect Sensitive Data**

   - Consider **column-level encryption** for sensitive fields.
   - Use **SSL/TLS** for database connections.
   - Implement **data masking** for non-admin users.


