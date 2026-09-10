"""Regression: safe prefix validation alone must not authorize source publication."""
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("review_bundle", HERE / "package-review-bundle.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
spec = importlib.util.spec_from_file_location("prefix_validation", HERE / "deploy-test-prefix.py")
prefix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prefix)


class PublicationInputTests(unittest.TestCase):
    def test_safe_but_unreviewed_archive_is_not_a_publication_input(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            data = b'{"test-only-private-material": "must not be collected"}'
            entry = tarfile.TarInfo(prefix.PREFIX + "/auth.json")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        candidate = output.getvalue()
        # This reproduces the original flaw: an allowed extraction path says
        # nothing about whether the file is a reviewed GPU distribution input.
        prefix.validate_archive(candidate)
        with self.assertRaisesRegex(ValueError, "independently reviewed"):
            review.validate_candidate(candidate)

    def test_real_candidate_and_appended_private_data(self):
        path = review.ROOT / "downloads/gpu/foldgpt-mesa-26.2.2-arm64.tar.gz"
        if not path.exists():
            self.skipTest("Build the independently reviewed candidate first")
        original = path.read_bytes()
        review.validate_candidate(original)
        with self.assertRaisesRegex(ValueError, "independently reviewed"):
            review.validate_candidate(original + b"test-only-private-trailing-data")


if __name__ == "__main__":
    unittest.main()
