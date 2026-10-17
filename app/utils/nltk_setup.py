"""Downloads the small NLTK datasets the project can use:  python -m app.utils.nltk_setup
The app still works without them (it falls back to built-in lists), but results are better with them."""
import nltk

PACKAGES = ["stopwords", "wordnet", "omw-1.4"]


def main() -> None:
    for package in PACKAGES:
        ok = nltk.download(package, quiet=True)
        print(f"{package}: {'ok' if ok else 'FAILED (check your internet connection)'}")


if __name__ == "__main__":
    main()
