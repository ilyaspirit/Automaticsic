import os
import sys

# Тяжёлые модули импортируются лениво, каждый в своей ветке: редактор
# и окно хода выполнения тянут PySide6, и грузить их обоих незачем.


def main():
    args = [a for a in sys.argv[1:] if a]
    edit = "--edit" in args
    files = [a for a in args if not a.startswith("--")]
    path = files[0] if files else None

    if path and not edit:
        if not os.path.isfile(path):
            print(f"Файл не найден: {path}")
            return 1
        import ui_progress
        return ui_progress.run_script_file(path)

    import editor
    return editor.run_editor(path)


if __name__ == "__main__":
    sys.exit(main())
