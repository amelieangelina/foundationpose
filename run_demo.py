# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.


from estimater import *
from datareader import *
import argparse


def main():
    """
    Main function to initialize and run the pose estimation and tracking.

    Parses command line arguments, sets up logging and seed, loads the mesh,
    initializes estimators, and processes each frame in the input video directory.
    """
    parser = argparse.ArgumentParser()

    # Get the directory of the current script
    code_dir = os.path.dirname(os.path.realpath(__file__))

    # Define arguments for the script
    parser.add_argument(
        "--mesh_file",
        type=str,
        default=f"{code_dir}/demo_data/44_correct/mesh/rubiks_cube_scaled.obj",
        help="Path to the mesh file",
    )
    parser.add_argument(
        "--test_scene_dir",
        type=str,
        default=f"{code_dir}/demo_data/44_correct",
        help="Path to the test scene directory",
    )
    parser.add_argument(
        "--est_refine_iter",
        type=int,
        default=5,
        help="Number of refinement iterations for estimation",
    )
    parser.add_argument(
        "--track_refine_iter",
        type=int,
        default=2,
        help="Number of refinement iterations for tracking",
    )
    parser.add_argument(
        "--debug",
        type=int,
        default=1,
        help="Debug level (0: no debug, 1: basic debug, 2: intermediate debug, 3: detailed debug)",
    )
    parser.add_argument(
        "--debug_dir",
        type=str,
        default=f"{code_dir}/debug",
        help="Directory to save debug information",
    )
    args = parser.parse_args()

    # Set logging format and seed
    set_logging_format()
    set_seed(0)

    # Load the mesh
    mesh = trimesh.load(args.mesh_file)

    # Debug settings
    debug = args.debug
    debug_dir = args.debug_dir
    os.system(
        f"rm -rf {debug_dir}/* && mkdir -p {debug_dir}/track_vis {debug_dir}/ob_in_cam"
    )

    # Determine the bounding box of the mesh
    to_origin, extents = trimesh.bounds.oriented_bounds(mesh)
    bbox = np.stack([-extents / 2, extents / 2], axis=0).reshape(2, 3)

    # Initialize estimators
    scorer = ScorePredictor()
    refiner = PoseRefinePredictor()
    glctx = dr.RasterizeCudaContext()
    est = FoundationPose(
        model_pts=mesh.vertices,
        model_normals=mesh.vertex_normals,
        mesh=mesh,
        scorer=scorer,
        refiner=refiner,
        debug_dir=debug_dir,
        debug=debug,
        glctx=glctx,
    )
    logging.info("Estimator initialization done")

    # Initialize the data reader
    reader = YcbineoatReader(
        video_dir=args.test_scene_dir, shorter_side=None, zfar=np.inf
    )

    # Process each frame in the input video directory
    for i in range(len(reader.color_files)):
        logging.info(f"Processing frame {i}")
        color = reader.get_color(i)
        depth = reader.get_depth(i)

        if i == 0:
            # Initial pose registration
            mask = reader.get_mask(0).astype(bool)
            pose = est.register(
                K=reader.K,
                rgb=color,
                depth=depth,
                ob_mask=mask,
                iteration=args.est_refine_iter,
            )

            if debug >= 3:
                m = mesh.copy()
                m.apply_transform(pose)
                m.export(f"{debug_dir}/model_tf.obj")
                xyz_map = depth2xyzmap(depth, reader.K)
                valid = depth >= 0.001
                pcd = toOpen3dCloud(xyz_map[valid], color[valid])
                o3d.io.write_point_cloud(f"{debug_dir}/scene_complete.ply", pcd)
        else:
            # Pose tracking
            pose = est.track_one(
                rgb=color, depth=depth, K=reader.K, iteration=args.track_refine_iter
            )

        # Save the pose to the debug directory
        os.makedirs(f"{debug_dir}/ob_in_cam", exist_ok=True)
        np.savetxt(f"{debug_dir}/ob_in_cam/{reader.id_strs[i]}.txt", pose.reshape(4, 4))

        if debug >= 1:
            # Visualize the pose
            center_pose = pose @ np.linalg.inv(to_origin)
            vis = draw_posed_3d_box(
                reader.K, img=color, ob_in_cam=center_pose, bbox=bbox
            )
            vis = draw_xyz_axis(
                color,
                ob_in_cam=center_pose,
                scale=0.1,
                K=reader.K,
                thickness=3,
                transparency=0,
                is_input_rgb=True,
            )
            cv2.imshow("Pose Visualization", vis[..., ::-1])
            cv2.waitKey(1)

        if debug >= 2:
            # Save visualization to the debug directory
            os.makedirs(f"{debug_dir}/track_vis", exist_ok=True)
            imageio.imwrite(f"{debug_dir}/track_vis/{reader.id_strs[i]}.png", vis)


if __name__ == "__main__":
    main()
