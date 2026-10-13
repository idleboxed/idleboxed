# Инструкции агента

Следуй [IDLE.md](IDLE.md); явные уточнения этого проекта имеют приоритет.

`idleboxed` — интеграционный репозиторий; Python-пакет и команда — `iboxed`.
Сабмодули — в `components/`, состав сборки — в `config.toml`, код — в `src/iboxed/`,
тесты — непосредственно в `tests/` (уточнение к IDLE.md). Рецепты компонентов принадлежат iroll.

Трамплин собирает и устанавливает только самостоятельный itrampoline;
в сборку iboxed и его архивы core/helper не входят.

Каждый архив содержит `system/release.json` и `system/THIRD_PARTY.txt`.
Внешний `release.json` нужен для публикации; отдельного asset `THIRD_PARTY.txt` нет.

Согласованный CLI: `iboxed build [--latest]`, `iboxed publish`.
Новые команды и параметры сначала согласовать с владельцем.

Уточнения к IDLE.md: установка — `uv tool install --force -e .`;
проверки — `ma tools`, `ma tests`, только Python 3.12; sdist включает тесты.
Использование и соглашения о выпусках — в [README.md](README.md),
разработка — в [docs/development.md](docs/development.md).
