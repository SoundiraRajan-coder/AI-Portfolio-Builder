import atexit
import queue
import ssl
import threading
import urllib.parse
from contextlib import contextmanager
from flask import current_app

class DatabaseError(Exception):
    """Base error for database configuration and connection failures."""


class DatabaseConfigurationError(DatabaseError):
    """Raised when the database connection string is not configured."""


class DatabaseConnectionError(DatabaseError):
    """Raised when PostgreSQL cannot be reached."""


# Try psycopg first, fallback to pure-Python pg8000 (immune to Windows AppLocker/DLL block policies)
_USE_PSYCOPG = False
try:
    from psycopg_pool import ConnectionPool
    from psycopg import Connection as _PsycopgConn
    _USE_PSYCOPG = True
except Exception:
    _USE_PSYCOPG = False


if not _USE_PSYCOPG:
    import pg8000.dbapi
    if not hasattr(pg8000.dbapi.Cursor, "__enter__"):
        pg8000.dbapi.Cursor.__enter__ = lambda self: self
        pg8000.dbapi.Cursor.__exit__ = lambda self, *args: self.close()

    class PG8000Pool:
        def __init__(self, database_url, min_size=2, max_size=10, timeout=10.0):
            self.database_url = database_url
            self.min_size = min_size
            self.max_size = max_size
            self.timeout = timeout
            self._pool = queue.Queue(maxsize=max_size)
            self._lock = threading.Lock()
            self._size = 0
            self._closed = False

            parsed = urllib.parse.urlparse(database_url)
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            self._conn_params = {
                "user": urllib.parse.unquote(parsed.username or "postgres"),
                "password": urllib.parse.unquote(parsed.password or ""),
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "database": parsed.path.lstrip("/") or "postgres",
                "timeout": timeout,
                "ssl_context": ssl_ctx,
            }

            for _ in range(min_size):
                try:
                    conn = self._create_connection()
                    self._pool.put_nowait(conn)
                    self._size += 1
                except Exception:
                    break

        def _create_connection(self):
            conn = pg8000.dbapi.connect(**self._conn_params)
            conn.autocommit = False
            return conn

        @property
        def closed(self):
            return self._closed

        @contextmanager
        def connection(self, timeout=None):
            if self._closed:
                raise DatabaseConnectionError("Connection pool is closed.")
            t = timeout or self.timeout
            conn = None
            try:
                conn = self._pool.get(block=False)
            except queue.Empty:
                with self._lock:
                    if self._size < self.max_size:
                        conn = self._create_connection()
                        self._size += 1
                if conn is None:
                    try:
                        conn = self._pool.get(block=True, timeout=t)
                    except queue.Empty:
                        raise DatabaseConnectionError("Database connection pool timeout.")

            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = self._create_connection()

            try:
                yield conn
            finally:
                if not self._closed:
                    try:
                        self._pool.put_nowait(conn)
                    except queue.Full:
                        try:
                            conn.close()
                        except Exception:
                            pass
                        with self._lock:
                            self._size -= 1
                else:
                    try:
                        conn.close()
                    except Exception:
                        pass

        def close(self):
            self._closed = True
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass


_pool = None


def _close_pool():
    global _pool
    if _pool is not None and not _pool.closed:
        try:
            _pool.close()
        except Exception:
            pass


atexit.register(_close_pool)


def get_pool():
    global _pool
    database_url = current_app.config.get("DATABASE_URL")
    if not database_url:
        raise DatabaseConfigurationError(
            "SUPABASE_DATABASE_URL is not configured."
        )

    if _pool is None or _pool.closed:
        if _USE_PSYCOPG:
            _pool = ConnectionPool(
                conninfo=database_url,
                min_size=2,
                max_size=10,
                timeout=10.0,
                open=True,
            )
        else:
            _pool = PG8000Pool(
                database_url=database_url,
                min_size=2,
                max_size=10,
                timeout=10.0,
            )
    return _pool


@contextmanager
def get_db_connection():
    """Checkout a PostgreSQL connection from the thread-safe connection pool."""
    pool = get_pool()
    try:
        with pool.connection() as connection:
            yield connection
    except (DatabaseConfigurationError, DatabaseConnectionError):
        raise
    except Exception as exc:
        raise DatabaseConnectionError from exc


def check_database_connection():
    """Run a minimal query and return True if reachable."""
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1


def init_pool(app):
    """Pre-initialize and warm up the database connection pool on application startup."""
    with app.app_context():
        try:
            pool = get_pool()
            with pool.connection(timeout=5.0) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            app.logger.info("Database connection pool initialized and warmed up.")
        except Exception as exc:
            app.logger.warning("Database connection pool startup warmup deferred: %s", exc)
