#!/usr/bin/env python3
import sys
import termios
import tty
import select
import time

import rclpy
from rclpy.node import Node

from std_msgs.msg import Float64MultiArray


class KeyboardDriveSteer(Node):
    """
    W: throttle up (0..1) -> effort 0..+max_effort (solo ruote posteriori)
    S: throttle down (0..-1) -> effort 0..-max_effort
    A/D: steer angle target -> posizione per entrambi i giunti sterzo (Float64MultiArray)

    Uses key-repeat to detect "held down".
    """

    def __init__(self):
        super().__init__('keyboard_drive_steer')

        # --- Parameters (edit or override via --ros-args -p ...) ---
        # NB: must match the JointGroupEffortController name in effort_control_config.yaml
        self.declare_parameter('effort_topic', '/wheel_group_effort_controller/commands')
        # order must match YAML joints list
        self.declare_parameter('wheel_joint_order', [
            'left_rear', 'right_rear'
        ])
        self.declare_parameter('max_effort', 10000.0)

        self.declare_parameter('steer_topic', '/steering_position_controller/commands')
        self.declare_parameter('steer_joint_order', ['left', 'right'])

        self.declare_parameter('throttle_ramp_per_sec', 1.2)     # 0..1 per second (quanto velocemente arriva al 100%)
        self.declare_parameter('throttle_decay_per_sec', 2.0)    # torna verso 0 quando non premi nulla
        self.declare_parameter('steer_ramp_rad_per_sec', 1.5)    # rad/s quando tieni A o D
        self.declare_parameter('steer_decay_rad_per_sec', 3.0)   # torna verso 0 quando non premi A/D
        self.declare_parameter('steer_max_rad', 0.6)             # limite sterzo
        self.declare_parameter('traj_time', 0.10)                # time_from_start per il trajectory point (s)

        self.declare_parameter('rate_hz', 50.0)
        self.declare_parameter('hold_timeout', 0.20)             # se non arrivano ripetizioni entro questo tempo => considerato rilasciato
        self.declare_parameter('tty_device', '/dev/tty')         # device da cui leggere i tasti (utile con ros2 launch)

        # Read params
        self.effort_topic = self.get_parameter('effort_topic').value
        self.max_effort = float(self.get_parameter('max_effort').value)
        self.wheel_joint_order = list(self.get_parameter('wheel_joint_order').value)

        self.steer_topic = self.get_parameter('steer_topic').value
        self.steer_joint_order = list(self.get_parameter('steer_joint_order').value)

        self.throttle_ramp_per_sec = float(self.get_parameter('throttle_ramp_per_sec').value)
        self.throttle_decay_per_sec = float(self.get_parameter('throttle_decay_per_sec').value)

        self.steer_ramp_rad_per_sec = float(self.get_parameter('steer_ramp_rad_per_sec').value)
        self.steer_decay_rad_per_sec = float(self.get_parameter('steer_decay_rad_per_sec').value)
        self.steer_max_rad = float(self.get_parameter('steer_max_rad').value)
        self.traj_time = float(self.get_parameter('traj_time').value)

        self.rate_hz = float(self.get_parameter('rate_hz').value)
        self.hold_timeout = float(self.get_parameter('hold_timeout').value)
        self.tty_device = str(self.get_parameter('tty_device').value)

        # Publishers
        self.eff_pub = self.create_publisher(Float64MultiArray, self.effort_topic, 10)
        self.steer_pub = self.create_publisher(Float64MultiArray, self.steer_topic, 10)

        # State
        self.throttle = 0.0   # [-1..1]
        self.steer = 0.0      # [rad]

        # Key "held" detection via last-seen time
        self.last_seen = {'w': -1.0, 's': -1.0, 'a': -1.0, 'd': -1.0}

        # Terminal raw mode setup (works even if launched via ros2 launch)
        try:
            self._tty = open(self.tty_device, 'rb', buffering=0)
            self._orig_term = termios.tcgetattr(self._tty.fileno())
            tty.setcbreak(self._tty.fileno())
        except Exception as exc:
            self.get_logger().error(
                f"Impossibile accedere a {self.tty_device} per leggere la tastiera: {exc}. "
                "Assicurati di lanciare il nodo in un terminale interattivo."
            )
            raise

        # Timer
        self._last_tick = time.monotonic()
        self.timer = self.create_timer(1.0 / self.rate_hz, self.tick)

        self.get_logger().info(
            "Keyboard control active:\n"
            "  W = accelerate forward\n"
            "  S = accelerate backward\n"
            "  A = steer left\n"
            "  D = steer right\n"
            "CTRL+C to quit\n"
            f"Effort topic: {self.effort_topic}\n"
            f"Steer topic: {self.steer_topic} order={self.steer_joint_order}"
        )

    def destroy_node(self):
        # Restore terminal
        try:
            termios.tcsetattr(self._tty.fileno(), termios.TCSADRAIN, self._orig_term)
        except Exception:
            pass
        try:
            self._tty.close()
        except Exception:
            pass
        super().destroy_node()

    def _read_keys_nonblocking(self):
        """Read all available chars from stdin (raw mode) without blocking."""
        keys = []
        while True:
            r, _, _ = select.select([self._tty], [], [], 0.0)
            if not r:
                break
            ch = self._tty.read(1)
            if ch:
                try:
                    keys.append(ch.decode('utf-8'))
                except Exception:
                    continue
        return keys

    def tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        # Read keyboard
        for ch in self._read_keys_nonblocking():
            c = ch.lower()
            if c in self.last_seen:
                self.last_seen[c] = now

        # Determine held keys
        def held(k: str) -> bool:
            t = self.last_seen[k]
            return (t > 0.0) and ((now - t) <= self.hold_timeout)

        w = held('w')
        s = held('s')
        a = held('a')
        d = held('d')

        # --- Throttle update ---
        # W drives throttle toward +1, S drives toward -1.
        # If both pressed, cancel.
        if w and not s:
            self.throttle += self.throttle_ramp_per_sec * dt
        elif s and not w:
            self.throttle -= self.throttle_ramp_per_sec * dt
        else:
            # decay to 0 when no command or conflicting
            if self.throttle > 0:
                self.throttle -= self.throttle_decay_per_sec * dt
            elif self.throttle < 0:
                self.throttle += self.throttle_decay_per_sec * dt

        # clamp
        if self.throttle > 1.0:
            self.throttle = 1.0
        if self.throttle < -1.0:
            self.throttle = -1.0
        # deadzone small
        if abs(self.throttle) < 1e-3 and not (w or s):
            self.throttle = 0.0

        # Map throttle -> effort
        effort = self.throttle * self.max_effort

        # Publish effort to rear axle (same torque on both)
        eff_msg = Float64MultiArray()
        eff_msg.data = [float(effort)] * 2
        self.eff_pub.publish(eff_msg)

        # --- Steering update ---
        # A toward +steer_max (left), D toward -steer_max (right) — invert if your convention differs
        if a and not d:
            self.steer += self.steer_ramp_rad_per_sec * dt
        elif d and not a:
            self.steer -= self.steer_ramp_rad_per_sec * dt
        else:
            # decay back to 0
            if self.steer > 0:
                self.steer -= self.steer_decay_rad_per_sec * dt
            elif self.steer < 0:
                self.steer += self.steer_decay_rad_per_sec * dt

        # clamp and deadzone
        if self.steer > self.steer_max_rad:
            self.steer = self.steer_max_rad
        if self.steer < -self.steer_max_rad:
            self.steer = -self.steer_max_rad
        if abs(self.steer) < 1e-3 and not (a or d):
            self.steer = 0.0

        # Publish steering as Float64MultiArray (left, right)
        steer_msg = Float64MultiArray()
        steer_msg.data = [float(self.steer), float(self.steer)]
        self.steer_pub.publish(steer_msg)


def main():
    rclpy.init()
    node = KeyboardDriveSteer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
