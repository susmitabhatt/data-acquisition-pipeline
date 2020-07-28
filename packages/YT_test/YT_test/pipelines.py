# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface

from .gcs_operations import *
from .pipeline_config import *
import glob
import json
import os
import subprocess
import moviepy.editor
import yaml
import pandas as pd

dictionary = {
    }

# Serializing json
json_object = json.dumps(dictionary, indent=4)

# Writing to sample.json
with open("credentials.json", "w") as outfile:
    outfile.write(json_object)

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'


class YTPipeline:
    FILE_FORMAT = 'mp4'
    ARCHIVE_FILE_NAME = 'archive.txt'
    VIDEO_BATCH_FILE_NAME = 'video_list.txt'

    def get_video_batch(self):
        os.system(
            "cat full_playlist.txt {0} | sed 's/youtube //g' | sort |uniq -c |awk '$1==1' | cut -c9- | head -{1} > {2} ".format(
                self.ARCHIVE_FILE_NAME, batch_num, self.VIDEO_BATCH_FILE_NAME))
        return int(subprocess.check_output(
            "cat {0} | wc -l".format(self.VIDEO_BATCH_FILE_NAME), shell=True).decode("utf-8").split('\n')[
                       0])

    def get_playlist_count(self, channel_url):
        os.system(
            '/app/python/bin/youtube-dl {0} --flat-playlist --get-id --match-title "{1}" --reject-title "{2}" > full_playlist.txt '.format(
                channel_url, match_title_string, reject_title_string))
        return int(subprocess.check_output(
            "cat full_playlist.txt | wc -l", shell=True).decode("utf-8").split('\n')[0])

    def get_archive_file_path(self):
        return channel_blob_path + '/' + archive_blob_path + '/' + source_name + '/' + self.ARCHIVE_FILE_NAME

    def config_yaml(self):
        config_path = os.path.dirname(os.path.realpath(__file__))
        print(os.listdir(config_path))
        config_file = config_path + '/config.py'
        config_yaml_file = config_file.replace('.py', '.yaml')
        os.rename(config_file, config_yaml_file)
        with open(config_yaml_file) as file:
            yml = yaml.load(file, Loader=yaml.FullLoader)
        return yml

    def create_metadata(self, video_info, yml):
        metadata = {'raw_file_name': video_info['raw_file_name'],
                    'duration': str(video_info['duration']),
                    'title': video_info['raw_file_name'],
                    'speaker_name': video_info['name'],
                    'audio_id': yml['audio_id'],
                    'cleaned_duration': yml['cleaned_duration'],
                    'num_of_speakers': yml['num_of_speakers'],  # check
                    'language': yml['language'],
                    'has_other_audio_signature': yml['has_other_audio_signature'],
                    'type': yml['type'],
                    'source': yml['source'],  # --------
                    'experiment_use': yml['experiment_use'],  # check
                    'utterances_file_list': yml['utterances_file_list'],
                    'source_url': video_info['source_url'],
                    'speaker_gender': video_info['gender'],
                    'source_website': yml['source_website'],  # --------
                    'experiment_name': yml['experiment_name'],
                    'mother_tongue': yml['mother_tongue'],
                    'age_group': yml['age_group'],  # -----------
                    'recorded_state': yml['recorded_state'],
                    'recorded_district': yml['recorded_district'],
                    'recorded_place': yml['recorded_place'],
                    'recorded_date': yml['recorded_date'],
                    'purpose': yml['purpose']}
        return metadata

    def process_item(self, item, spider):
        print(
            "**********************************************YOUTUBE DOWNLOAD STARTS*****************************************************************")
        batch_count = 0
        print("Downloading videos for source : ", source_name)
        try:
            if check_blob(bucket, self.get_archive_file_path()):
                download_blob(bucket, self.get_archive_file_path(), self.ARCHIVE_FILE_NAME)
                print("Archive file has been downloaded from bucket {0} to local path...".format(bucket))
                num_downloaded = sum(1 for line in open(self.ARCHIVE_FILE_NAME))
                print("Count of Previously downloaded files are : ", num_downloaded)
            else:
                os.system('touch {0}'.format(self.ARCHIVE_FILE_NAME))
                print("No Archive file has been found on bucket...Downloading all files...")
        finally:
            playlist_count = self.get_playlist_count(channel_url)
            print("Total playlist count with valid videos is ", playlist_count)
            last_video_batch_count = self.get_video_batch()
            while last_video_batch_count > 0:

                print("Attempt to download videos with batch size of ", last_video_batch_count)
                try:
                    os.system(
                        '/app/python/bin/youtube-dl -f bestvideo[ext=mp4] -ciw -o "%(title)s_:file-id%(id)s.%(ext)s" -v --batch-file {0}  --restrict-filenames --download-archive {1} --proxy "" --abort-on-error '.format(
                            self.VIDEO_BATCH_FILE_NAME, self.ARCHIVE_FILE_NAME))
                finally:
                    video_info = {}
                    yml_config = self.config_yaml()['downloader']
                    audio_paths = glob.glob('*.' + self.FILE_FORMAT)
                    audio_files_count = len(audio_paths)
                    if audio_files_count > 0:
                        batch_count += audio_files_count
                        print("Uploading {0} files to gcs bucket...".format(audio_files_count))
                        for file in audio_paths:
                            meta_file_name = file.replace('mp4', 'csv')
                            source_url = ("https://www.youtube.com/watch?v=") + (file.split(':file-id')[-1][:-4])
                            video = moviepy.editor.VideoFileClip(file)
                            video_duration = int(video.duration) / 60
                            video_info['duration'] = video_duration
                            video_info['raw_file_name'] = file
                            video_info['name'] = None
                            video_info['gender'] = None
                            video_info['source_url'] = source_url
                            metadata = self.create_metadata(video_info, yml_config)
                            metadata_df = pd.DataFrame([metadata])
                            metadata_df.to_csv(meta_file_name, index=False)
                            # print("The duration of {0} is  {1}".format(file, video_duration))
                            upload_blob(bucket, file,
                                        channel_blob_path + '/' + source_name + '/' + file)
                            os.remove(file)
                            upload_blob(bucket, meta_file_name,
                                        channel_blob_path + '/' + source_name + '/' + meta_file_name)
                            os.remove(meta_file_name)
                        upload_blob(bucket, self.ARCHIVE_FILE_NAME,
                                    channel_blob_path + '/' + archive_blob_path + '/' + source_name + '/' + self.ARCHIVE_FILE_NAME)
                        print("Uploaded files till now: ", batch_count)
                last_video_batch_count = self.get_video_batch()
            print("Last Batch has no more videos to be downloaded,so finishing downloads...")
            print("Total Uploaded files for this run was : ", batch_count)
