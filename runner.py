import datetime
import os
import time

import actions
import model


class Log:
    def __init__(self, on_line=None):
        self.lines = []
        self.on_line = on_line
        self.has_error = False
        self.last_error = None

    def write(self, text, level="info"):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {text}"
        self.lines.append(line)
        if level == "error":
            self.has_error = True
            self.last_error = text.strip()
        if self.on_line:
            self.on_line(line, level)

    def info(self, text):
        self.write(text)

    def error(self, text):
        self.write(text, "error")

    def dump_to_file(self, script_path):
        if not script_path:
            return None
        path = os.path.splitext(script_path)[0] + ".log"
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n===== {stamp} =====\n")
            f.write("\n".join(self.lines))
            f.write("\n")
        return path


def step_prefix(index=None):
    """Номер шага в начале каждой его строки: «Шаг 2. ».

    Отступов у продолжений нет намеренно: одна строка лога — одна законченная
    запись, и по любой из них видно, к какому шагу она относится.
    """
    return f"Шаг {index}. " if index else ""


def sentence(text):
    """С большой буквы — строка лога читается как предложение.

    Обработчики шагов и тексты ошибок пишутся строчными: их подставляют
    и в середину фразы тоже. Заглавную ставим здесь, в одном месте, где
    строка окончательно собрана.
    """
    text = str(text)
    return text[:1].upper() + text[1:]


def line(prefix, text):
    return f"{prefix}{sentence(text)}"


def run_step(step, ctx, log, index=None):
    handler = actions.HANDLERS.get(step["type"])

    if handler is None:
        raise actions.StepError(f"действие «{step['type']}» ещё не реализовано")

    prefix = step_prefix(index)
    log.info(line(prefix, model.step_title(step)))
    result = handler(step, ctx)
    if result:
        log.info(line(prefix, result))
    return result


def run_script(script, log, script_path=None, should_stop=None, on_progress=None):
    ctx = actions.Context(script, script_path, should_stop)
    steps = script.get("steps", [])
    pause = script.get("autopause_ms", 200) / 1000.0

    log.info(f"Старт: {model.steps_word(len(steps))}")

    for index, step in enumerate(steps, 1):
        prefix = step_prefix(index)

        if ctx.stop_requested():
            log.info("Прервано")
            return False

        if on_progress:
            # Отдаём и сам шаг: по названию значок не соберёшь, а лезть
            # за ним в ядро незачем — это дело интерфейса.
            on_progress(index, len(steps), model.step_title(step), step)

        if not step.get("enabled", True):
            log.info(line(prefix, model.step_title(step)))
            log.info(line(prefix, "пропущен: шаг выключен"))
            continue

        try:
            run_step(step, ctx, log, index)
        except actions.StepError as e:
            if step.get("ignore_error"):
                log.info(line(prefix, f"ошибка пропущена: {e}"))
            else:
                log.error(line(prefix, f"ошибка: {e}"))
                # В пузыре при двойном клике видна одна строка, поэтому
                # номер шага нужен и там.
                log.last_error = f"Шаг {index}: {sentence(e)}"
                log.info("Остановлено")
                return False
        except Exception as e:
            # Второй перехват — для всего, что не StepError: пусть сценарий
            # останавливается внятной строкой, а не трассировкой.
            if step.get("ignore_error"):
                log.info(line(prefix, f"ошибка пропущена: {e!r}"))
            else:
                log.error(line(prefix, f"непредвиденная ошибка: {e!r}"))
                log.last_error = f"Шаг {index}: непредвиденная ошибка {e!r}"
                log.info("Остановлено")
                return False

        if pause and index < len(steps):
            time.sleep(pause)

    if ctx.stop_requested():
        log.info("Прервано")
        return False

    log.info("Готово")
    return True
