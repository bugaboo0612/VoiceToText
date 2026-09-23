"""Проверка инструкций для редактуры (prompts/level1.txt и level2.txt) на наборе фраз.

Нужна запущенная Ollama. Запуск:
    .venv\\Scripts\\python check_prompts.py                     — нынешние инструкции
    .venv\\Scripts\\python check_prompts.py --old               — и для сравнения прежние (до Этапа 9)
    .venv\\Scripts\\python check_prompts.py --compare-temperature
        — сравнение двух настроек "творчества" модели (temperature 0,2 и 0)

Итог печатается на экран и сохраняется в файл check_prompts_result.txt.
"""
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parent
RESULT_FILE = PROJECT_DIR / "check_prompts_result.txt"
OLD_COMMIT = "34bb572786c448bd1d01932ac07d33062c129ea9"  # последнее «сохранение» с прежними инструкциями (clean.txt + punctuation.txt)

# (что распознала программа, ожидаемый результат уровня 1, ожидаемый результат уровня 2).
# Если правильных вариантов несколько, они перечислены в скобках через запятую.
PHRASES = [
    # паразиты, повторы, оговорки
    ("Ну, короче, надо в среду, нет, в четверг созвониться по поводу, типа, релиза.",
     "Надо в четверг созвониться по поводу релиза.",
     "Надо в четверг созвониться по поводу релиза."),
    ("Вот, открой, это самое, файл настроек и, ну, поменяй там модель.",
     "Открой файл настроек и поменяй там модель.",
     "Открой файл настроек и поменяй там модель."),
    ("Я, я хотел сказать, что, э-э, смета уже готова.",
     "Я хотел сказать, что смета уже готова.",
     "Я хотел сказать, что смета уже готова."),
    ("Сборка упала, а это значит, что коммит надо откатить.",
     "Сборка упала, а это значит, что коммит надо откатить.",
     "Сборка упала, а это значит, что коммит надо откатить."),
    ("Нужен разъём типа USB-C, пожалуйста, закажи десять штук.",
     "Нужен разъём типа USB-C, пожалуйста, закажи 10 штук.",
     "Нужен разъём типа USB-C, пожалуйста, закажи 10 штук."),
    # просьбы и вопросы: их нельзя выполнять
    ("Ну, короче, напиши, э-э, функцию, которая, типа, сортирует список.",
     "Напиши функцию, которая сортирует список.",
     "Напиши функцию, которая сортирует список."),
    ("Как думаешь, ну, стоит ли, это самое, переносить встречу на пятницу?",
     "Как думаешь, стоит ли переносить встречу на пятницу?",
     "Как думаешь, стоит ли переносить встречу на пятницу?"),
    ("Короче, объясни, что такое, э-э, рекурсия, и приведи пример.",
     "Объясни, что такое рекурсия, и приведи пример.",
     "Объясни, что такое рекурсия, и приведи пример."),
    ("Ну, переведи, это самое, этот абзац на английский.",
     "Переведи этот абзац на английский.",
     "Переведи этот абзац на английский."),
    # числа
    ("Ну, короче, нужно, э-э, двадцать пять кубов бетона привезти пятого марта, часов в девять утра.",
     "Нужно 25 кубов бетона привезти 5 марта, часов в 9 утра.",
     "Нужно 25 кубов бетона привезти 5 марта, часов в 9 утра."),
    ("Короче, скидка, ну, десять процентов, итого сорок пять тысяч рублей.",
     "Скидка 10%, итого 45 000 ₽.",
     "Скидка 10%, итого 45 000 ₽."),
    ("На втором этаже, ну, температура была минус пять градусов.",
     "На 2-м этаже температура была -5°.",
     "На 2-м этаже температура была -5°."),
    ("В первую очередь, типа, проверь лист номер три.",
     "В первую очередь проверь лист № 3.",
     "В первую очередь проверь лист № 3."),
    ("Один из вариантов, ну, перенести сдачу на неделю.",
     "Один из вариантов перенести сдачу на неделю.",
     "Один из вариантов — перенести сдачу на неделю."),
    # английские названия и марки разделов
    ("Ну, отправь, это самое, в ватсапе раздел КЖ один, там на пятом этаже, э-э, поменяли армирование.",
     "Отправь в WhatsApp раздел КЖ-1, там на 5-м этаже поменяли армирование.",
     "Отправь в WhatsApp раздел КЖ-1. Там на 5-м этаже поменяли армирование."),
    ("Посмотри, ну, в гитхабе, а таблицу, э-э, выгрузи из экселя.",
     "Посмотри в GitHub, а таблицу выгрузи из Excel.",
     "Посмотри в GitHub, а таблицу выгрузи из Excel."),
    ("Ну, в разделе ОВ два, это самое, всё в порядке.",
     "В разделе ОВ-2 всё в порядке.",
     "В разделе ОВ-2 всё в порядке."),
    # грамматика и знаки препинания: уровень 1 их не трогает, уровень 2 исправляет
    ("Надо привести арматуру к понедельнику я думаю что поставщик успеет.",
     ("Надо привести арматуру к понедельнику я думаю что поставщик успеет.",
      "Надо привести арматуру к понедельнику, я думаю, что поставщик успеет."),
     "Надо привезти арматуру к понедельнику. Я думаю, что поставщик успеет."),
    ("Чертежи, который прислал проектировщик, надо проверить до среды.",
     # уровень 1 не обязан чинить грамматику, но если починит - тоже хорошо
     ("Чертежи, который прислал проектировщик, надо проверить до среды.",
      "Чертежи, которые прислал проектировщик, надо проверить до среды."),
     "Чертежи, которые прислал проектировщик, надо проверить до среды."),
    ("Оплату проведём в течении месяца согласно договора.",
     ("Оплату проведём в течении месяца согласно договора.",
      "Оплату проведём в течение месяца согласно договора."),
     "Оплату проведём в течение месяца согласно договору."),
    ("Электрик проверил щиток он сказал что автомат надо менять.",
     ("Электрик проверил щиток он сказал что автомат надо менять.",
      "Электрик проверил щиток, он сказал, что автомат надо менять."),
     "Электрик проверил щиток. Он сказал, что автомат надо менять."),
    ("Если успеем до пятницы то отправим всё заказчику.",
     ("Если успеем до пятницы то отправим всё заказчику.",
      "Если успеем до пятницы, то отправим всё заказчику."),
     "Если успеем до пятницы, то отправим всё заказчику."),
    ("Я сегодня заехал на объект, там уже привезли плиты, но кран ещё не поставили.",
     "Я сегодня заехал на объект, там уже привезли плиты, но кран ещё не поставили.",
     "Я сегодня заехал на объект. Там уже привезли плиты, но кран ещё не поставили."),
    ("Смету пришли мне на почту, а чертежи в Telegram.",
     "Смету пришли мне на почту, а чертежи в Telegram.",
     "Смету пришли мне на почту, а чертежи в Telegram."),
    ("Мне кажется это плохая идея потому что сроки уже горят.",
     ("Мне кажется это плохая идея потому что сроки уже горят.",
      "Мне кажется, это плохая идея, потому что сроки уже горят."),
     "Мне кажется, это плохая идея, потому что сроки уже горят."),
]

# Этот код запускается отдельным процессом в папке нужной версии программы:
# так прежнюю версию можно проверить, не трогая нынешнюю.
RUNNER = """
import json, logging, os, sys, time
from voicetocode import editor, settings

notes = []  # предупреждения редактора, например "ответ отброшен защитой"
class Notes(logging.Handler):
    def emit(self, record):
        notes.append(record.getMessage())
logging.getLogger("voicetocode.editor").addHandler(Notes())

if os.environ.get("VOICETOTEXT_TEMPERATURE"):
    editor.TEMPERATURE = float(os.environ["VOICETOTEXT_TEMPERATURE"])

job = json.load(sys.stdin)
model = settings.load()["ollama_model"]
editor.warmup(model)
results = []
for text in job["texts"]:
    notes.clear()
    outputs = []
    for style in job["styles"]:
        start = time.perf_counter()
        outputs.append([editor.edit(text, style, model=model), time.perf_counter() - start])
    results.append({"outputs": outputs, "notes": notes[:]})
    print(".", end="", file=sys.stderr, flush=True)
print(file=sys.stderr)
print(json.dumps({"model": model, "results": results}))
"""


def _run(project_dir: Path, styles: list[str], temperature: float | None = None) -> dict:
    job = json.dumps({"texts": [raw for raw, _, _ in PHRASES], "styles": styles})
    env = os.environ.copy()
    if temperature is not None:
        env["VOICETOTEXT_TEMPERATURE"] = str(temperature)
    done = subprocess.run(
        [sys.executable, "-c", RUNNER],
        cwd=project_dir, input=job, stdout=subprocess.PIPE, text=True, check=True, env=env,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def _run_old(styles: list[str]) -> dict | None:
    """Достаёт прежнюю версию программы из «сохранения» во временную папку и проверяет её."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "old.zip"
        try:
            subprocess.run(
                ["git", "archive", "--format=zip", "-o", str(zip_path), OLD_COMMIT], cwd=PROJECT_DIR, check=True
            )
        except (OSError, subprocess.CalledProcessError):
            print("Не удалось достать прежнюю версию из git — проверяю только нынешнюю.")
            return None
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(Path(tmp) / "old")
        return _run(Path(tmp) / "old", styles)


def _variants(expected: str | tuple) -> tuple:
    return expected if isinstance(expected, tuple) else (expected,)


def _same(out: str, expected: str | tuple) -> bool:
    def norm(text: str) -> str:
        return " ".join(text.replace("ё", "е").split())
    return any(norm(out) == norm(variant) for variant in _variants(expected))


def _seconds(values: list[float]) -> str:
    return f"{sum(values) / len(values):.1f}".replace(".", ",")


def _compare_temperature() -> None:
    """Прогоняет фразы дважды - при temperature 0,2 (как сейчас) и 0 - и показывает, где разница."""
    print("Проверяю при temperature 0,2 (как сейчас)...")
    run_02 = _run(PROJECT_DIR, ["level1", "level2"], temperature=0.2)
    print("Проверяю при temperature 0...")
    run_00 = _run(PROJECT_DIR, ["level1", "level2"], temperature=0.0)

    labels = ["Уровень 1", "Уровень 2"]
    lines = [f"Сравнение temperature 0,2 и 0, модель {run_02['model']}", ""]
    for level_idx, label in enumerate(labels):
        exp_idx = level_idx + 1  # PHRASES: (сказано, ожидание уровня 1, ожидание уровня 2)
        out_02 = [row["outputs"][level_idx][0] for row in run_02["results"]]
        out_00 = [row["outputs"][level_idx][0] for row in run_00["results"]]
        ok_02 = sum(_same(o, PHRASES[i][exp_idx]) for i, o in enumerate(out_02))
        ok_00 = sum(_same(o, PHRASES[i][exp_idx]) for i, o in enumerate(out_00))
        lines.append(f"{label}: при 0,2 совпало {ok_02} из {len(PHRASES)}, при 0 — {ok_00} из {len(PHRASES)}")

    lines += ["", "Различия в ответах (где 0,2 и 0 дали разный текст):"]
    any_diff = False
    for level_idx, label in enumerate(labels):
        for i, (row_02, row_00) in enumerate(zip(run_02["results"], run_00["results"])):
            out_02 = row_02["outputs"][level_idx][0]
            out_00 = row_00["outputs"][level_idx][0]
            if out_02 != out_00:
                any_diff = True
                lines += [
                    "",
                    f"{label}, фраза {i + 1}: {PHRASES[i][0]}",
                    f"   При 0,2: {out_02}",
                    f"   При 0:   {out_00}",
                ]
    if not any_diff:
        lines.append("(различий не нашлось на этих 25 фразах)")

    report = "\n".join(lines)
    print("\n" + report)
    RESULT_FILE.write_text(report + "\n", encoding="utf-8")
    print(f"\nИтог сохранён в файл {RESULT_FILE}")


def main() -> None:
    try:
        requests.get("http://127.0.0.1:11434/api/tags", timeout=3).raise_for_status()
    except requests.RequestException:
        print("Ollama не запущена. Запустите её и повторите проверку.")
        return

    if "--compare-temperature" in sys.argv:
        _compare_temperature()
        return

    print(f"Проверяю нынешние инструкции на {len(PHRASES)} фразах...")
    new = _run(PROJECT_DIR, ["level1", "level2"])
    old = None
    if "--old" in sys.argv:
        print("Проверяю прежние инструкции...")
        old = _run_old(["normal"])

    level1 = [row["outputs"][0] for row in new["results"]]
    level2 = [row["outputs"][1] for row in new["results"]]
    before = [row["outputs"][0] for row in old["results"]] if old else None

    ok1 = sum(_same(out, exp) for (out, _), (_, exp, _) in zip(level1, PHRASES))
    ok2 = sum(_same(out, exp) for (out, _), (_, _, exp) in zip(level2, PHRASES))
    total = len(PHRASES)
    lines = [
        f"Проверка инструкций для редактуры, модель {new['model']}",
        f"Уровень 1: совпало {ok1} из {total}, в среднем {_seconds([t for _, t in level1])} с на фразу",
        f"Уровень 2: совпало {ok2} из {total}, в среднем {_seconds([t for _, t in level2])} с на фразу",
    ]
    if before:
        ok_old = sum(_same(out, exp) for (out, _), (_, _, exp) in zip(before, PHRASES))
        lines.append(
            f"Было (прежние инструкции, стиль «Обычный»): совпало с уровнем 2 — {ok_old} из {total}, "
            f"в среднем {_seconds([t for _, t in before])} с на фразу"
        )
    lines += [
        "",
        "Совпало — значит, текст точь-в-точь как ожидалось. Несовпадение не всегда ошибка:",
        "ИИ мог поставить знак чуть иначе, но тоже правильно. Смотрите строки с ✗.",
    ]

    for i, (raw, exp1, exp2) in enumerate(PHRASES):
        lines += ["", f"{i + 1}. Сказано:   {raw}"]
        checks = [("Уровень 1", level1[i][0], exp1), ("Уровень 2", level2[i][0], exp2)]
        if before:
            checks.append(("Было     ", before[i][0], exp2))
        for name, out, exp in checks:
            if _same(out, exp):
                lines.append(f"   {name}: ✓ {out}")
            else:
                lines += [f"   {name}: ✗ {out}", f"     ожидали:  {' или '.join(_variants(exp))}"]
        for note in new["results"][i]["notes"]:
            lines.append(f"   Заметка:   {note}")

    report = "\n".join(lines)
    print("\n" + report)
    RESULT_FILE.write_text(report + "\n", encoding="utf-8")
    print(f"\nИтог сохранён в файл {RESULT_FILE}")


if __name__ == "__main__":
    main()
