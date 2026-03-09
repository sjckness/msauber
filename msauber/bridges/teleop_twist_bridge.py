import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TwistStamped

class teleop_twist_bridge(Node):

    def __init__(self):
        super().__init__('twist_bridge')

        self.sub = self.create_subscription(
            Twist,
            '/cmd_vel',
            self.callback,
            10
        )

        self.pub = self.create_publisher(
            TwistStamped,
            '/ackermann_steering_controller/reference',
            10
        )

    def callback(self, msg):
        out = TwistStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = "base_link"
        out.twist = msg
        self.pub.publish(out)

def main():
    rclpy.init()
    node = teleop_twist_bridge()
    rclpy.spin(node)

if __name__ == '__main__':
    main()