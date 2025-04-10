# volume-delta

## Prerequisites

1. **Python 3.x** installed on your system.
2. A **Polygon.io** account to obtain your `POLYGON_API_KEY`.
3. A `.env` file containing a valid `POLYGON_API_KEY` in the same directory as the script.

   ```
   POLYGON_API_KEY=your_polygon_api_key_here
   ```

## Setup and Installation

1. **Install poetry** (if not already installed):
   The recommended way to install Poetry on Ubuntu (including 22.04) is via the official installation script. You can run:

    ```bash
    curl -sSL https://install.python-poetry.org | python3 -
    ```

    After the installation completes, make sure you add Poetry to your `PATH`. By default, Poetry is installed under `~/.local/bin`:

    ```bash
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    source ~/.bashrc
    ```

    Finally, verify that Poetry is correctly installed:

    ```bash
    poetry --version
    ```

    That’s it! Now you can use Poetry to manage your Python projects.
   
2. Ensure you have placed your `POLYGON_API_KEY` in the `.env` file.
   
3. **Install the dependencies** (only needed once, or whenever you update `pyproject.toml`):
   ```bash
   poetry install
   ```
   This will read the dependencies listed in `pyproject.toml` (and potentially `poetry.lock`) and install them into the Poetry-managed virtual environment.

4. **Run your script**:
   ```bash
   poetry run python vd.py nvda 
   ```
   Here:
   - `nvda` is the **stock ticker** (e.g., NVDA for NVIDIA).


If you *already* ran `poetry install` sometime earlier (and nothing changed in `pyproject.toml`), you should be able to directly run the script using the same `poetry run ...` command without reinstalling. 

5. **Windows**
   ```bash
   poetry add windows-curses
   ```
