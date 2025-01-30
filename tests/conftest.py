# tests/conftest.py
import pytest
import os
from pyodbc import connect, Error

@pytest.fixture(scope="session")
def mssql_connection():
    """Create a test database connection."""
    try:
        connection = connect(
            host=os.getenv("MSSQL_HOST", "localhost"),
            user=os.getenv("MSSQL_USER", "root"),
            password=os.getenv("MSSQL_PASSWORD", "testpassword"),
            database=os.getenv("MSSQL_DATABASE", "test_db")
        )
        
        if connection.is_connected():
            # Create a test table
            cursor = connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_table (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255),
                    value INT
                )
            """)
            connection.commit()
            
            yield connection
            
            # Cleanup
            cursor.execute("DROP TABLE IF EXISTS test_table")
            connection.commit()
            cursor.close()
            connection.close()
            
    except Error as e:
        pytest.fail(f"Failed to connect to MSSQL: {e}")

@pytest.fixture(scope="session")
def mssql_cursor(mssql_connection):
    """Create a test cursor."""
    cursor = mssql_connection.cursor()
    yield cursor
    cursor.close()