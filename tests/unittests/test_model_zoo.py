import mxnet as mx
from autogluon.model_zoo import get_model

def test_image_classification_models():
    model_list = ['standford_dog_resnet152_v1', 'standford_dog_resnext101_64x4d']
    x = mx.nd.random.uniform((1, 3, 224, 224))
    for model_name in model_list:
        # get the model
        net = get_model(model_name, pretrained=True)
        # test inference
        y = net(x)

if __name__ == '__main__':
    test_image_classification_models()
