import os
import xacro
from pathlib import Path
from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    AppendEnvironmentVariable,
    TimerAction,
    OpaqueFunction,
)
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression, TextSubstitution, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():

    world_name = 'my_empty'

    use_sim_time = LaunchConfiguration('use_sim_time', default='true')

    gz_start_delay = DeclareLaunchArgument(
        'gz_start_delay',
        default_value='2.0',
        description='Seconds to let Gazebo start before launching bridges and nodes'
    )
    world_load_delay = DeclareLaunchArgument(
        'world_load_delay',
        default_value='1.0',
        description='Extra seconds to wait for the world to settle before spawning the robot'
    )

    pkg_share = os.path.join(get_package_share_directory('msauber'))

    gz_env = [
        AppendEnvironmentVariable(name='GZ_SIM_RESOURCE_PATH', value=pkg_share, separator=':'),
        AppendEnvironmentVariable(name='GZ_SIM_RESOURCE_PATH', value=os.path.join(pkg_share, 'models'), separator=':'),
        AppendEnvironmentVariable(name='GZ_SIM_RESOURCE_PATH', value=os.path.join(pkg_share, 'worlds'), separator=':'),
        AppendEnvironmentVariable(name='GZ_SIM_RESOURCE_PATH', value=os.path.join(pkg_share, 'description'), separator=':'),
        AppendEnvironmentVariable(name='GZ_SIM_RESOURCE_PATH', value=os.path.join(pkg_share, 'description', 'mesh'), separator=':'),
    ]

    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use Gazebo simulation time'
    )

    world_arg = DeclareLaunchArgument(
        'world',
        default_value=TextSubstitution(text=world_name),
        description='World name (without .sdf) located in msauber/worlds'
    )

    world_file = PathJoinSubstitution([
        FindPackageShare('msauber'),
        'worlds',
        LaunchConfiguration('world')
    ])
    
    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                FindPackageShare('ros_gz_sim').find('ros_gz_sim'),
                'launch',
                'gz_sim.launch.py'
            )
        ),
        launch_arguments={
            # passiamo il PATH ASSOLUTO + estensione
            'gz_args': [world_file, TextSubstitution(text='.sdf'), TextSubstitution(text=' -v 5 -r')]
        }.items()
    ) 

    xacro_file = os.path.join(pkg_share,
                              'description',
                              'msauber.xacro')
    
    doc = xacro.process_file(
        xacro_file,
        mappings={
            'use_sim': 'true',
            'pkg_share': pkg_share,
            'robot_name': 'sauber'
        }
    )

    robot_desc = doc.toprettyxml(indent='  ')

    params = {'robot_description': robot_desc}

    # spawn coordinates chosen per world name; defaults to my_empty
    spawn_poses = {
        'my_empty': {'x': '0.0', 'y': '0.0', 'z': '5', 'yaw': '3.14159'},
        'sonoma': {'x': '280.0', 'y': '-135.0', 'z': '5', 'yaw': '-0.78'},
    }

    def make_spawn_entity(context):
        world = LaunchConfiguration('world').perform(context)
        pose = spawn_poses.get(world, spawn_poses['my_empty'])
        return [Node(
            package='ros_gz_sim',
            executable='create',
            output='screen',
            arguments=[
                '-string', robot_desc,
                '-x', pose['x'],
                '-y', pose['y'],
                '-z', pose['z'],
                '-R', '0.0',
                '-P', '0.0',
                '-Y', pose['yaw'],
                '-name', 'msauber',
                '-allow_renaming', 'false'
            ],
        )]

    spawn_entity = OpaqueFunction(function=make_spawn_entity)
    
    node_robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[params, {'use_sim_time': use_sim_time}]
    )

    #joint state broadcaster for feedback on joints positions (no sensors used)
    load_joint_state_broadcaster= ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'joint_state_broadcaster'],
        output='screen'
    )

    # multi-effort controller for wheels
    load_wheel_effort_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'wheel_group_effort_controller'],
        output='screen'
    )

    # position controller for steering hinges
    load_steering_position_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'steering_position_controller'],
        output='screen'
    )

    # ackerman controller for spin and stear
    load_ackerman_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'ackermann_steering_controller'],
        output='screen'
    )

    twist_bridge = Node(
        package='msauber',
        executable='teleop_twist_bridge',
        name='teleop_twist_bridge',
        output='screen',
        parameters=[{'use_sim_time': use_sim_time}]
    )

    teleop = Node(
        package='teleop_twist_keyboard',
        executable='teleop_twist_keyboard',
        name='teleop_keyboard',
        output='screen',
        prefix='xterm -e',
        parameters=[{'use_sim_time': use_sim_time}]
    )

    # Timers to give Gazebo time to open and the world to load before spawning the robot.
    delayed_spawn_and_controllers = TimerAction(
        period=LaunchConfiguration('world_load_delay'),
        actions=[
            spawn_entity,
            load_joint_state_broadcaster,
            load_ackerman_controller,
            twist_bridge,
            teleop
            #load_wheel_effort_controller,
            #load_steering_position_controller
        ],
    )

    delayed_nodes = TimerAction(
        period=LaunchConfiguration('gz_start_delay'),
        actions=[
            node_robot_state_publisher,
            delayed_spawn_and_controllers,
        ],
    )

    return LaunchDescription([
        *gz_env,
        use_sim_time_arg,
        world_arg,
        gz_start_delay,
        world_load_delay,
        gz_sim,
        delayed_nodes
    ])
