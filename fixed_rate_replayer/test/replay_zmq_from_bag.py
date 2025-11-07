#!/usr/bin/env python3
import argparse
import datetime
import importlib
import json
import os
import sys
import time

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

import zmq


def iso_utc_now():
  return datetime.datetime.now(datetime.timezone.utc).isoformat()


def try_deserialize(topic_type, cdr_bytes):
  try:
    msg_type = get_message(topic_type)
    return deserialize_message(cdr_bytes, msg_type)
  except Exception:
    return None


def extract_pose(msg):
  try:
    p = msg.pose.position
    o = msg.pose.orientation
    return [p.x, p.y, p.z, o.x, o.y, o.z, o.w]
  except Exception:
    try:
      # geometry_msgs/msg/Pose
      p = msg.position
      o = msg.orientation
      return [p.x, p.y, p.z, o.x, o.y, o.z, o.w]
    except Exception:
      return [0.0]*7


def extract_gamepad(msg):
  # Expecting fields: pose (geometry_msgs/Pose), buttons (list[int]), axes (list[float])
  try:
    pose = extract_pose(msg)
  except Exception:
    pose = [0.0]*7
  try:
    buttons = list(msg.buttons)
  except Exception:
    buttons = []
  try:
    axes = list(msg.axes)
  except Exception:
    axes = []
  return pose, buttons, axes
 


def main():
  parser = argparse.ArgumentParser(description="Replay VR data from rosbag2 over ZMQ as JSON at fixed Hz")
  parser.add_argument('--bag', required=True, help='Path to rosbag2 directory (contains metadata.yaml)')
  parser.add_argument('--left_topic', default='/vr_left_gamepad')
  parser.add_argument('--right_topic', default='/vr_right_gamepad')
  parser.add_argument('--viewer_topic', default='/vr_viewer')
  # Match mocap_data_replay.py default: bind on all interfaces
  parser.add_argument('--address', default='tcp://*:5555')
  parser.add_argument('--hz', type=float, default=90.0)
  args = parser.parse_args()

  context = zmq.Context()
  sock = context.socket(zmq.PUB)
  # Align behavior with mocap script
  sock.setsockopt(zmq.LINGER, 0)
  try:
    # SNDHWM may not exist on some builds, guard with try
    sock.setsockopt(zmq.SNDHWM, 1000)
  except Exception:
    pass
  sock.bind(args.address)
  time.sleep(0.5)

  left_axes = [0.0]*15
  right_axes = [0.0]*15
  left_buttons = []
  right_buttons = []
  left_pose = [0.0]*7
  right_pose = [0.0]*7
  head_pose = [0.0]*7

  storage_options = rosbag2_py.StorageOptions(uri=args.bag, storage_id='sqlite3')
  converter_options = rosbag2_py.ConverterOptions('', '')
  reader = rosbag2_py.SequentialReader()
  reader.open(storage_options, converter_options)

  topic_types = {}
  for info in reader.get_all_topics_and_types():
    topic_types[info.name] = info.type

  # Read all bag data first, store snapshots
  bag_snapshots = []  # List of (left_pose, right_pose, head_pose) tuples
  snapshot_count = 0
  while reader.has_next():
    (topic, data, t) = reader.read_next()
    updated = False
    if topic == args.left_topic or topic == args.right_topic:
      msg = try_deserialize(topic_types.get(topic, ''), data)
      if msg is not None:
        pose, buttons, axes = extract_gamepad(msg)
        pose_7 = pose[:7]
        if topic == args.left_topic:
          left_pose = list(pose_7)  # Create new list
          left_axes = (axes + [0.0]*(15 - len(axes)))[:15] if len(axes) < 15 else axes[:15]
          updated = True
        else:
          right_pose = list(pose_7)  # Create new list
          right_axes = (axes + [0.0]*(15 - len(axes)))[:15] if len(axes) < 15 else axes[:15]
          updated = True
    elif topic == args.viewer_topic:
      msg = try_deserialize(topic_types.get(topic, ''), data)
      if msg is not None:
        head_pose = list(extract_pose(msg))  # Create new list
        updated = True
      
      # Store snapshot whenever any topic updates
      if updated:
        bag_snapshots.append((list(left_pose), list(right_pose), list(head_pose)))
        snapshot_count += 1
        if snapshot_count <= 5:  # Debug first 5 snapshots
          print(f"[DEBUG] Snapshot {snapshot_count}: left={left_pose[:3]}... right={right_pose[:3]}... head={head_pose[:3]}...")
  # reader is automatically closed when it goes out of scope

  print(f"[DEBUG] Total bag snapshots: {len(bag_snapshots)}")

  # Print first few and last few snapshots for debugging
  if len(bag_snapshots) > 0:
    print(f"[DEBUG] First 3 snapshots:")
    for i in range(min(1000, len(bag_snapshots))):
      left, right, head = bag_snapshots[i]
      print(f"  [{i}] left={left[:3]}... right={right[:3]}... head={head[:3]}...")
    if len(bag_snapshots) > 6:
      print(f"[DEBUG] Last 3 snapshots:")
      for i in range(max(1000, len(bag_snapshots) - 3), len(bag_snapshots)):
        left, right, head = bag_snapshots[i]
        print(f"  [{i}] left={left[:3]}... right={right[:3]}... head={head[:3]}...")


  if len(bag_snapshots) == 0:
    print("[WARN] No data found in bag")
    return

  # Replay snapshots at fixed Hz
  rate = 1.0 / max(args.hz, 1.0)
  next_tick = time.time()
  snapshot_idx = 0

  try:
    while True:
      now = time.time()
      if now >= next_tick:
        if snapshot_idx < len(bag_snapshots):
          current_left, current_right, current_head = bag_snapshots[snapshot_idx]
          if snapshot_idx < 10 or snapshot_idx % 100 == 0:  # Debug first 10 or every 100th
            print(f"[DEBUG] Using snapshot {snapshot_idx}: left={current_left[:3]}... right={current_right[:3]}... head={current_head[:3]}...")
          snapshot_idx += 1
        else:
          break  # finished all snapshots

        # Build 175-length hand arrays from pose7 + zeros, keep original payload fields
        left_hand = current_left + [0.0]*168
        right_hand = current_right + [0.0]*168
        hand_payload = {
          "timestamp": iso_utc_now(),
          "handedness": "hand",
          "left_right_hand_dict": {"left": left_hand, "right": right_hand},
          "left_right_gamepad_dict": {"left": (current_left + [0.0]*8)[:15], "right": (current_right + [0.0]*8)[:15]}
        }
        print(f"[{time.time():.3f}] hand_data")
        # sock.send_multipart([b"hand_data", json.dumps(hand_payload).encode('utf-8')])

        # Keep original head payload structure with timestamp
        head = {"timestamp": iso_utc_now(), "head_pose": current_head}
        print(f"[{time.time():.3f}] head")
        print(f"[DEBUG] head: {head}")
        sock.send_multipart([b"head", json.dumps(head).encode('utf-8')])

        # Build gamepad payload with original fields; 15-length per side from pose7 + controls
        def make_gamepad(pose7):
          base = list(pose7[:7])
          controls = [0.0, 0.0, -100.0, 0.0, -100.0, -100.0, 0.0, 0.0]
          return (base + controls)[:15]
        payload = {
          "timestamp": iso_utc_now(),
          "handedness": "gamepad",
          "left_right_hand_dict": {"left": left_hand, "right": right_hand},
          "left_right_gamepad_dict": {"left": make_gamepad(current_left), "right": make_gamepad(current_right)}
        }
        print(f"[{time.time():.3f}] gamepad_data")
        print(f"[DEBUG] gamepad_data payload: {payload}")
        sock.send_multipart([b"gamepad_data", json.dumps(payload).encode('utf-8')])

        next_tick += rate
        if now > next_tick + rate:
          next_tick = now + rate

      time.sleep(0.001)
  except KeyboardInterrupt:
    pass

  # Finished replaying snapshots; exit
  # no ROS_AVAILABLE fallback path needed

  sock.close()
  context.term()


if __name__ == '__main__':
  main()

