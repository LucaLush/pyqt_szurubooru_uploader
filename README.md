# overview
This is a gui application for uploading images to szurubooru
# env
```shell
pip install pyqt5 pyszuru
```
# usage
- open GUI
```shell
python ./uploader.py
```
- enter szurubooru URL such like http://192.168.1.110
- enter token you can find token in szurubooru website "account->Login tokens"
- enter tags that were seperated by spaces
- Drag and drop files or press select files button to choose which images to upload
- Press the upload button and wait for completion

The parameters you enter will be saved to a file named settings in the root directory.
