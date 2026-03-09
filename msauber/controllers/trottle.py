#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

class DualWheelEffortPublisher(Node):
    def __init__(self):
        super().__init__('dual_wheel_effort_publisher')

        self.declare_parameter('topic', '/wheel_group_effort_controller/commands')
        self.declare_parameter('effort', 1000.0)   # coppia per ciascun joint
        self.declare_parameter('rate', 50.0)

        self.topic = self.get_parameter('topic').value
        self.effort = float(self.get_parameter('effort').value)
        rate = float(self.get_parameter('rate').value)

        self.pub = self.create_publisher(Float64MultiArray, self.topic, 10)
        self.timer = self.create_timer(1.0 / rate, self.cb)

        self.get_logger().info(
            f'Publishing same effort={self.effort} to 2 joints on {self.topic} at {rate} Hz'
        )

    def cb(self):
        msg = Float64MultiArray()
        msg.data = [self.effort, self.effort]  # stesso effort su entrambi i joint
        self.pub.publish(msg)

def main():
    rclpy.init()
    node = DualWheelEffortPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()