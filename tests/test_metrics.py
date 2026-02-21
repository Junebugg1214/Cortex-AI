"""
Tests for cortex.caas.metrics — Counter, Gauge, Histogram, MetricsRegistry.
"""

import threading

from cortex.caas.metrics import Counter, Gauge, Histogram, MetricsRegistry

# ---------------------------------------------------------------------------
# Counter tests
# ---------------------------------------------------------------------------

class TestCounter:
    def test_basic_inc(self):
        c = Counter("test_total", "A test counter")
        c.inc()
        c.inc()
        c.inc(3.0)
        assert c.get() == 5.0

    def test_labeled_inc(self):
        c = Counter("requests_total", "Requests", label_names=("method", "status"))
        c.inc(method="GET", status="200")
        c.inc(method="GET", status="200")
        c.inc(method="POST", status="201")
        assert c.get(method="GET", status="200") == 2.0
        assert c.get(method="POST", status="201") == 1.0
        assert c.get(method="GET", status="404") == 0.0

    def test_collect_format(self):
        c = Counter("my_counter", "Help text")
        c.inc(5.0)
        lines = c.collect()
        assert "# HELP my_counter Help text" in lines
        assert "# TYPE my_counter counter" in lines
        assert "my_counter 5.0" in lines

    def test_collect_with_labels(self):
        c = Counter("req", "", label_names=("method",))
        c.inc(method="GET")
        lines = c.collect()
        assert any('method="GET"' in line for line in lines)

    def test_thread_safety(self):
        c = Counter("thread_safe", "", label_names=("worker",))
        errors = []

        def inc_many(worker_id):
            try:
                for _ in range(1000):
                    c.inc(worker=str(worker_id))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=inc_many, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        total = sum(c.get(worker=str(i)) for i in range(5))
        assert total == 5000.0


# ---------------------------------------------------------------------------
# Gauge tests
# ---------------------------------------------------------------------------

class TestGauge:
    def test_set_and_get(self):
        g = Gauge("temperature", "Current temperature")
        g.set(42.5)
        assert g.get() == 42.5

    def test_inc_dec(self):
        g = Gauge("in_flight", "In-flight requests")
        g.inc()
        g.inc()
        g.dec()
        assert g.get() == 1.0

    def test_labeled_gauge(self):
        g = Gauge("active", "", label_names=("pool",))
        g.set(10.0, pool="a")
        g.set(20.0, pool="b")
        assert g.get(pool="a") == 10.0
        assert g.get(pool="b") == 20.0

    def test_collect_format(self):
        g = Gauge("mem_usage", "Memory")
        g.set(100.0)
        lines = g.collect()
        assert "# TYPE mem_usage gauge" in lines
        assert "mem_usage 100.0" in lines

    def test_thread_safety(self):
        g = Gauge("gauge_test", "")
        errors = []

        def set_many():
            try:
                for i in range(1000):
                    g.set(float(i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=set_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ---------------------------------------------------------------------------
# Histogram tests
# ---------------------------------------------------------------------------

class TestHistogram:
    def test_observe(self):
        h = Histogram("latency", "Latency", buckets=(0.1, 0.5, 1.0))
        h.observe(0.05)
        h.observe(0.3)
        h.observe(0.7)
        h.observe(2.0)
        lines = h.collect()
        assert "# TYPE latency histogram" in lines
        # Check bucket lines
        assert any("latency_bucket" in line and 'le="0.1"' in line for line in lines)
        assert any("latency_sum" in line for line in lines)
        assert any("latency_count" in line and "4" in line for line in lines)

    def test_bucket_accumulation(self):
        h = Histogram("test_hist", "", buckets=(1.0, 5.0, 10.0))
        h.observe(0.5)  # <= 1.0, <= 5.0, <= 10.0
        h.observe(3.0)  # <= 5.0, <= 10.0
        h.observe(7.0)  # <= 10.0
        h.observe(15.0)  # none
        lines = h.collect()
        # Bucket cumulative: le=1.0 -> 1, le=5.0 -> 2, le=10.0 -> 3, +Inf -> 4
        bucket_lines = [line for line in lines if "test_hist_bucket" in line]
        assert any('le="1.0"' in line and " 1" in line for line in bucket_lines)
        # Find the actual values from the bucket lines
        bucket_map = {}
        for line in bucket_lines:
            for le in ["1.0", "5.0", "10.0", "+Inf"]:
                if f'le="{le}"' in line:
                    val = line.strip().split()[-1]
                    bucket_map[le] = int(val)
        assert bucket_map.get("1.0") == 1
        assert bucket_map.get("5.0") == 2
        assert bucket_map.get("10.0") == 3
        assert bucket_map.get("+Inf") == 4

    def test_labeled_histogram(self):
        h = Histogram("http_duration", "", label_names=("method",), buckets=(0.1, 1.0))
        h.observe(0.05, method="GET")
        h.observe(0.5, method="POST")
        lines = h.collect()
        assert any('method="GET"' in line for line in lines)
        assert any('method="POST"' in line for line in lines)

    def test_thread_safety(self):
        h = Histogram("thread_hist", "", buckets=(0.1, 0.5, 1.0))
        errors = []

        def observe_many():
            try:
                for i in range(500):
                    h.observe(i * 0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=observe_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ---------------------------------------------------------------------------
# MetricsRegistry tests
# ---------------------------------------------------------------------------

class TestMetricsRegistry:
    def test_collect_empty(self):
        reg = MetricsRegistry()
        output = reg.collect()
        assert output.strip() == ""  # empty output

    def test_collect_single_metric(self):
        reg = MetricsRegistry()
        c = Counter("test_total", "Test")
        reg.register(c)
        c.inc(5.0)
        output = reg.collect()
        assert "# TYPE test_total counter" in output
        assert "test_total 5.0" in output

    def test_collect_multiple_metrics(self):
        reg = MetricsRegistry()
        c = Counter("requests", "Requests")
        g = Gauge("active", "Active")
        reg.register(c)
        reg.register(g)
        c.inc()
        g.set(10.0)
        output = reg.collect()
        assert "# TYPE requests counter" in output
        assert "# TYPE active gauge" in output

    def test_prometheus_text_format(self):
        reg = MetricsRegistry()
        c = Counter("http_total", "Total HTTP requests", label_names=("method",))
        reg.register(c)
        c.inc(method="GET")
        c.inc(method="GET")
        c.inc(method="POST")
        output = reg.collect()
        lines = output.strip().split("\n")
        # Should have HELP, TYPE, and two data lines
        assert any(line.startswith("# HELP http_total") for line in lines)
        assert any(line.startswith("# TYPE http_total") for line in lines)
        assert any('method="GET"' in line and "2.0" in line for line in lines)
        assert any('method="POST"' in line and "1.0" in line for line in lines)


# ---------------------------------------------------------------------------
# Instrumentation module tests
# ---------------------------------------------------------------------------

class TestInstrumentation:
    def test_create_default_registry(self):
        from cortex.caas.instrumentation import create_default_registry
        reg = create_default_registry()
        output = reg.collect()
        assert "cortex_http_requests_total" in output
        assert "cortex_http_request_duration_seconds" in output
        assert "cortex_http_requests_in_flight" in output
        assert "cortex_grants_active" in output
        assert "cortex_graph_nodes" in output
        assert "cortex_graph_edges" in output
        assert "cortex_errors_total" in output
        assert "cortex_build_info" in output
        assert 'version="1.0.0"' in output
