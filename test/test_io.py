import os
import contextlib
import tempfile
import torch
import torchvision.io as io
import unittest


try:
    import av
except ImportError:
    av = None


def _create_video_frames(num_frames, height, width):
    y, x = torch.meshgrid(torch.linspace(-2, 2, height), torch.linspace(-2, 2, width))
    data = []
    for i in range(num_frames):
        xc = float(i) / num_frames
        yc = 1 - float(i) / (2 * num_frames)
        d = torch.exp(-((x - xc) ** 2 + (y - yc) ** 2) / 2) * 255
        data.append(d.unsqueeze(2).repeat(1, 1, 3).byte())

    return torch.stack(data, 0)


@contextlib.contextmanager
def temp_video(num_frames, height, width, fps, lossless=False, video_codec=None, options=None):
    if lossless:
        assert video_codec is None, "video_codec can't be specified together with lossless"
        assert options is None, "options can't be specified together with lossless"
        video_codec = 'libx264rgb'
        options = {'crf': '0'}

    if video_codec is None:
        video_codec = 'libx264'
    if options is None:
        options = {}

    data = _create_video_frames(num_frames, height, width)
    with tempfile.NamedTemporaryFile(suffix='.mp4') as f:
        io.write_video(f.name, data, fps=fps, video_codec=video_codec, options=options)
        yield f.name, data


class Tester(unittest.TestCase):
    # compression adds artifacts, thus we add a tolerance of
    # 6 in 0-255 range
    TOLERANCE = 6

    @unittest.skipIf(av is None, "PyAV unavailable")
    def test_write_read_video(self):
        with temp_video(10, 300, 300, 5, lossless=True) as (f_name, data):
            lv, _, info = io.read_video(f_name)

            self.assertTrue(data.equal(lv))
            self.assertEqual(info["video_fps"], 5)

    @unittest.skipIf(av is None, "PyAV unavailable")
    def test_read_timestamps(self):
        with temp_video(10, 300, 300, 5) as (f_name, data):
            pts, _ = io.read_video_timestamps(f_name)

            # note: not all formats/codecs provide accurate information for computing the
            # timestamps. For the format that we use here, this information is available,
            # so we use it as a baseline
            container = av.open(f_name)
            stream = container.streams[0]
            pts_step = int(round(float(1 / (stream.average_rate * stream.time_base))))
            num_frames = int(round(float(stream.average_rate * stream.time_base * stream.duration)))
            expected_pts = [i * pts_step for i in range(num_frames)]

            self.assertEqual(pts, expected_pts)

    @unittest.skipIf(av is None, "PyAV unavailable")
    def test_read_partial_video(self):
        with temp_video(10, 300, 300, 5, lossless=True) as (f_name, data):
            pts, _ = io.read_video_timestamps(f_name)
            for start in range(5):
                for l in range(1, 4):
                    lv, _, _ = io.read_video(f_name, pts[start], pts[start + l - 1])
                    s_data = data[start:(start + l)]
                    self.assertEqual(len(lv), l)
                    self.assertTrue(s_data.equal(lv))

            lv, _, _ = io.read_video(f_name, pts[4] + 1, pts[7])
            self.assertEqual(len(lv), 4)
            self.assertTrue(data[4:8].equal(lv))

    @unittest.skipIf(av is None, "PyAV unavailable")
    def test_read_partial_video_bframes(self):
        # do not use lossless encoding, to test the presence of B-frames
        options = {'bframes': '16', 'keyint': '10', 'min-keyint': '4'}
        with temp_video(100, 300, 300, 5, options=options) as (f_name, data):
            pts, _ = io.read_video_timestamps(f_name)
            for start in range(0, 80, 20):
                for l in range(1, 4):
                    lv, _, _ = io.read_video(f_name, pts[start], pts[start + l - 1])
                    s_data = data[start:(start + l)]
                    self.assertEqual(len(lv), l)
                    self.assertTrue((s_data.float() - lv.float()).abs().max() < self.TOLERANCE)

            lv, _, _ = io.read_video(f_name, pts[4] + 1, pts[7])
            self.assertEqual(len(lv), 4)
            self.assertTrue((data[4:8].float() - lv.float()).abs().max() < self.TOLERANCE)

    # TODO add tests for audio


if __name__ == '__main__':
    unittest.main()
