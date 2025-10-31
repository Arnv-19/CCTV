import json
import os
import numpy as np

ROI_CONFIG_FILE = "config/rois.json"

def load_rois():
    """
    Loads ROIs from the JSON file and returns a dictionary
    with cam_id (str) as key and NumPy array as value.
    """
    rois_np_dict = {}
    if not os.path.exists(ROI_CONFIG_FILE):
        return rois_np_dict  # Return empty dict if file doesn't exist
    
    try:
        with open(ROI_CONFIG_FILE, 'r') as f:
            json_data = json.load(f)
        
        for cam_id, points in json_data.items():
            if points and len(points) == 4:
                rois_np_dict[str(cam_id)] = np.array(points, dtype=np.int32)
                
    except Exception as e:
        print(f"[ERROR] Failed to load ROI config: {e}")
    
    return rois_np_dict

def save_rois(rois_dict):
    """
    Saves the ROI dictionary (which uses NumPy arrays)
    to the JSON config file (as lists).
    """
    rois_list_dict = {}
    for cam_id, arr in rois_dict.items():
        if arr is not None:
            rois_list_dict[str(cam_id)] = arr.tolist()
            
    try:
        with open(ROI_CONFIG_FILE, 'w') as f:
            json.dump(rois_list_dict, f, indent=4)
    except Exception as e:
        print(f"[ERROR] Failed to save ROI config: {e}")