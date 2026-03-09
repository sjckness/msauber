import os
import xacro
from pathlib import Path
from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.actions import RegisterEventHandler, SetEnvironmentVariable
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():
    world_name = 'empty'

    use_sim_time = LaunchConfiguration('use_sim_time', default=False)

    pkg_share = os.path.join(get_package_share_directory('msauber'))

    gazebo_resource_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=os.path.join(pkg_share,'worlds')
    )

    arguments = LaunchDescription([
                DeclareLaunchArgument('world', default_value=world_name,     #name of the world.sdf file in /worlds folder
                          description='Gz sim World'),
           ]
    )

    
    pkg_ros_gz_sim = FindPackageShare('ros_gz_sim').find('ros_gz_sim')

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_ros_gz_sim, 'launch', 'gz_sim.launch.py')
        ),
        launch_arguments={
            'gz_args': PythonExpression([
                "'",
                LaunchConfiguration('world'),
                ".sdf -v 4 -r'"
            ])
        }.items()
    )

    xacro_file = os.path.join(pkg_share,
                              'description',
                              'macros.xacro')
    
    doc = xacro.process_file(xacro_file, mappings={'use_sim' : 'true'})

    robot_desc = doc.toprettyxml(indent='  ')

    params = {'robot_description': robot_desc}
    
    node_robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[params]
    )

    gz_spawn_entity = Node(
        package='ros_gz_sim',
        executable='create',
        output='screen',
        arguments=['-string', robot_desc,
                   '-x', '-1.0',
                   '-y', '0.0',
                   '-z', '5',     #spawn at .5 meters from the ground
                   '-R', '0.0',
                   '-P', '0.0',
                   '-Y', '3.14159',
                   '-name', 'msauber',
                   '-allow_renaming', 'false'],
    )
    #joint state broadcaster for feedback on joints positions (no sensors used)
    load_joint_state_broadcaster= ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'joint_state_broadcaster'],
        output='screen'
    )

    #multi effort controller
    load_joint_effort_controller = ExecuteProcess(
        cmd=['ros2', 'control', 'load_controller', '--set-state', 'active',
             'wheel_group_effort_controller'],
        output='screen'
    )

    return LaunchDescription([
        gazebo_resource_path,
        arguments,
        gz_sim,
        node_robot_state_publisher,
        gz_spawn_entity,
        load_joint_state_broadcaster,
        load_joint_effort_controller
    ])