from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from .decoder import decode
from .effects.engine import State
from .generators import generate
from .scenes.runtime import SceneStore


class SourceTimeline:
    """At most two simultaneous segment decoders; no transition frame queue."""

    def __init__(self, plan, ffmpeg, output, features=None):
        self.plan, self.ffmpeg, self.output = plan, ffmpeg, output
        self.active = {}
        self.transitions = {t["incoming"]: t for t in plan.get("transitions", [])}
        self.tails = {t["outgoing"]: t["end"] - t["start"] for t in plan.get("transitions", [])}
        self.cursor = 0
        self.generator_states = {}
        self.scene_store = SceneStore(plan["config"], output, features)

    def __enter__(self):
        return self

    def __exit__(self, *error):
        cleanup = ExitStack()
        for stack, _ in self.active.values():
            cleanup.push(stack)
        cleanup.callback(self.scene_store.close)
        return cleanup.__exit__(*error)

    def open(self, number, index):
        clip = self.plan["clips"][number]
        tail = self.tails.get(number, 0)
        count = clip["end"] - clip["start"]
        specification = dict(clip)
        if clip["source"] is None:
            self.active[number] = ExitStack(), None
            return
        specification["source_duration"] = self.plan["media"][clip["source"]]["duration"]
        if specification["reverse"] and tail:
            specification["offset"] = (
                specification["offset"] - tail / float(self.output.fps_fraction) * clip["speed"]
            ) % specification["source_duration"]
        stack = ExitStack()
        try:
            frames = stack.enter_context(
                decode(
                    self.ffmpeg,
                    Path(self.plan["media"][clip["source"]]["path"]),
                    specification,
                    self.output,
                    count + tail,
                )
            )
            for _ in range(index - clip["start"]):
                next(frames)
        except BaseException:
            stack.close()
            raise
        self.active[number] = stack, frames

    def at(self, index, context):
        clips = self.plan["clips"]
        while self.cursor + 1 < len(clips) and clips[self.cursor]["end"] <= index:
            self.cursor += 1
        current = self.cursor
        transition = self.transitions.get(current)
        if transition and index >= transition["end"]:
            transition = None
        needed = {current, transition["outgoing"]} if transition else {current}
        for number in list(self.active):
            if number not in needed:
                stack, _ = self.active.pop(number)
                stack.close()
        frames = {}
        for number in sorted(needed):
            if number not in self.active:
                self.open(number, index)
            iterator = self.active[number][1]
            frame = next(iterator) if iterator is not None else None
            clip = clips[number]
            if "scene" in clip:
                frame = self.scene_store.frame(clip, index, context, frame)
            elif clip.get("generator") and index < clip["generator_end"]:
                local = replace(
                    context,
                    clip_id=clip["start"],
                    clip_time=(index - clip["start"]) / context.fps,
                    raw_frame=frame,
                )
                state = self.generator_states.setdefault(clip["generator"], State())
                frame = generate(
                    clip["generator"], self.output.resolution, local, clip.get("generator_params", {}), state
                )
            frames[number] = frame
        return (
            clips[current],
            frames[current],
            (frames[transition["outgoing"]] if transition else None),
            transition,
        )
