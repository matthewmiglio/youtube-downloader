"""
Credentials manager for YouTube API key storage and retrieval.
"""
import json
import os
from pathlib import Path


class CredsManager:
    """Manages API credentials stored in a local JSON file."""

    def __init__(self, creds_file: str = "credentials.json"):
        """
        Initialize the credentials manager.

        Args:
            creds_file: Path to the credentials JSON file
        """
        self.creds_file = Path(creds_file)

    def load_creds(self) -> dict:
        """
        Load credentials from the JSON file.

        Returns:
            Dictionary containing credentials

        Raises:
            FileNotFoundError: If credentials file doesn't exist
            ValueError: If API key is not set
        """
        if not self.creds_file.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.creds_file}\n"
                f"Run 'python creds.py' to create a default credentials file."
            )

        with open(self.creds_file, 'r') as f:
            creds = json.load(f)

        if not creds.get('api_key') or creds.get('api_key') == 'YOUR_API_KEY_HERE':
            raise ValueError(
                "API key not set in credentials file. "
                "Please edit credentials.json and add your YouTube API key."
            )

        return creds

    def get_api_key(self) -> str:
        """
        Get the YouTube API key.

        Returns:
            The API key string
        """
        creds = self.load_creds()
        return creds['api_key']

    def create_default_creds_file(self):
        """Create a default credentials file with placeholder values."""
        default_creds = {
            'api_key': 'YOUR_API_KEY_HERE',
            'description': 'Replace YOUR_API_KEY_HERE with your YouTube Data API v3 key'
        }

        with open(self.creds_file, 'w') as f:
            json.dump(default_creds, f, indent=4)

        print(f"Created default credentials file: {self.creds_file}")
        print("Please edit this file and add your YouTube API key.")


if __name__ == "__main__":
    # When run directly, create the default credentials file
    manager = CredsManager()

    if manager.creds_file.exists():
        print(f"Credentials file already exists: {manager.creds_file}")
        response = input("Overwrite? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            exit(0)

    manager.create_default_creds_file()
