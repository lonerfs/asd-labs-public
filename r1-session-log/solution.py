#!/usr/bin/env python3
"""Разбор журнала сессий стеком.

Запуск:
    python solution.py вход.txt выход.txt      # обычный разбор
    python solution.py --bench                 # замеры по протоколу курса
"""
import io
import platform
import statistics
import sys
import time


# ============================== стек ==============================

class _Node:
    __slots__ = ("value", "next")

    def __init__(self, value, next_node=None):
        self.value = value
        self.next = next_node


class Stack:
    __slots__ = ("_head", "_size")

    def __init__(self):
        self._head = None
        self._size = 0

    def push(self, value):
        self._head = _Node(value, self._head)
        self._size += 1

    def pop(self):
        if self._head is None:
            raise IndexError("pop from empty stack")
        node = self._head
        self._head = node.next
        self._size -= 1
        return node.value

    def top(self):
        if self._head is None:
            raise IndexError("top from empty stack")
        return self._head.value

    def is_empty(self):
        return self._head is None

    def __len__(self):
        return self._size

    def drain_bottom_up(self):
        buf = []
        node = self._head
        while node is not None:
            buf.append(node.value)
            node = node.next
        self._head = None
        self._size = 0
        return reversed(buf)


#разбор

def parse_event(line):
    s = line.strip()
    if not s:
        return "SKIP"
    parts = s.split()
    if len(parts) != 2:
        return None
    kind, name = parts
    if kind not in ("LOGIN", "LOGOUT"):
        return None
    if not name.isascii() or not name.isalnum():
        return None
    return kind, name


def process(stream, out):
    stack = Stack()
    errors = []
    sessions = 0
    for line_no, raw in enumerate(stream, start=1):
        ev = parse_event(raw)
        if ev == "SKIP":
            continue
        if ev is None:
            errors.append((line_no, "bad_event"))
            continue
        kind, name = ev
        if kind == "LOGIN":
            stack.push((name, line_no))
        else:
            if stack.is_empty():
                errors.append((line_no, "logout_without_login"))
            elif stack.top()[0] != name:
                errors.append((line_no, "order_violation"))
            else:
                stack.pop()
                sessions += 1
    for name, ln in stack.drain_bottom_up():
        errors.append((ln, "session_not_closed"))
    for ln, code in errors:
        out.write(f"ERROR {ln} {code}\n")
    out.write(f"SESSIONS {sessions}\n")


#режим замеров

BENCH_SEED     = 42           #фиксированный сид, повтор даёт те же числа
BENCH_WARMUP   = 3            #холостых прогонов, результаты отбрасываются
BENCH_REPEATS  = 7            #замеров на точку, в отчёт идёт медиана
BENCH_MIN_TIME = 0.010        #нижняя граница: точки короче 10 мс невалидны
BENCH_SIZES = [40_000, 80_000, 160_000, 320_000, 640_000, 1_280_000]  # удвоение, 6 точек


def _gen_log(n, seed=BENCH_SEED):
    """Сбалансированный журнал из ~n строк."""
    half = n // 2
    lines = [f"LOGIN u{i}" for i in range(half)]
    lines += [f"LOGOUT u{i}" for i in reversed(range(half))]
    return "\n".join(lines) + "\n"
def _gen_log_worst(n, seed=BENCH_SEED):
    """Худший случай по памяти: n LOGIN подряд, ни одного LOGOUT."""
    return "\n".join(f"LOGIN u{i}" for i in range(n)) + "\n"

def _bench_run_once(text):
    """Один прогон разбора. Возвращает (время, строка_вывода)."""
    buf = io.StringIO()
    t0 = time.perf_counter()
    process(io.StringIO(text), buf)
    t1 = time.perf_counter()
    return t1 - t0, buf.getvalue()


def bench():
    """Замеры роста"""
    print(f"# Платформа:  {platform.platform()}")
    print(f"# Процессор:  {platform.processor() or 'н/д'}")
    print(f"# Python:     {sys.version.split()[0]}")
    print(f"# Часы:       time.perf_counter (монотонные)")
    print(f"# Протокол:   прогрев {BENCH_WARMUP}, повторов {BENCH_REPEATS}, сид {BENCH_SEED}")
    print()

    header = (f"{'n':>10}  {'медиана, с':>12}  {'мин, с':>10}  "
              f"{'макс, с':>10}  {'разброс, %':>11}  {'t/n, нс':>10}")
    print(header)
    print("-" * len(header))

    checksum = ""
    valid_points = 0

    for n in BENCH_SIZES:
        text = _gen_log(n)

        # прогрев — результаты отбрасываются
        for _ in range(BENCH_WARMUP):
            _, checksum = _bench_run_once(text)

        # серия замеров
        times = []
        for _ in range(BENCH_REPEATS):
            dt, checksum = _bench_run_once(text)
            times.append(dt)

        med = statistics.median(times)
        lo, hi = min(times), max(times)
        spread = (hi - lo) / med * 100 if med else 0.0
        per_event_ns = med / n * 1e9

        mark = "" if med >= BENCH_MIN_TIME else "  ← ниже 10 мс, исключить"
        if med >= BENCH_MIN_TIME:
            valid_points += 1

        print(f"{n:>10}  {med:>12.6f}  {lo:>10.6f}  {hi:>10.6f}  "
              f"{spread:>11.2f}  {per_event_ns:>10.1f}{mark}")

    # защита от оптимизатора: результат обязан использоваться
    print()
    print(f"# контрольная сумма последнего прогона: {sum(map(ord, checksum))}")

    if valid_points < 6:
        print()
        print(f"# внимание: валидных точек {valid_points}, протокол требует ≥ 6")
        print(f"# подними BENCH_SIZES, чтобы все точки были > 10 мс")


#запуск

def _strip_posix_quotes(p):
    """check.py оборачивает пути через shlex.quote (POSIX-стиль, одинарные кавычки).
    На Windows cmd.exe их не снимает, и аргумент доходит до нас буквально
    как  'C:\\path\\to\\file'.  Убираем кавычки, если они есть.""" #deepseek
    if len(p) >= 2 and p[0] == "'" and p[-1] == "'":
        return p[1:-1]
    return p


def main(argv):
    # режим замеров: solution.py --bench
    if len(argv) == 2 and argv[1] == "--bench":
        bench()
        return 0

    if len(argv) != 3:
        print("использование: solution.py вход.txt выход.txt", file=sys.stderr)
        print("              solution.py --bench", file=sys.stderr)
        return 2

    in_path  = _strip_posix_quotes(argv[1])
    out_path = _strip_posix_quotes(argv[2])

    try:
        with open(in_path, "r", encoding="utf-8", errors="replace") as f, \
                open(out_path, "w", encoding="utf-8") as out:
            process(f, out)
    except OSError as e:
        print(f"ошибка файла: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))