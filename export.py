import os

import tensorflow as tf
from google.protobuf import text_format
from tensorflow.python.tools.freeze_graph import freeze_graph_with_def_protos

from protos import pipeline_pb2
from builders import model_builder


slim = tf.contrib.slim

flags = tf.app.flags

flags.DEFINE_string('input_shape', None,
                    'If input_type is `image_tensor`, this can explicitly set '
                    'the shape of this input tensor to a fixed size. The '
                    'dimensions are to be provided as a comma-separated list '
                    'of integers. A value of -1 can be used for unknown '
                    'dimensions. If not specified, for an `image_tensor, the '
                    'default shape will be partially specified as '
                    '`[None, None, None, 3]`.')
flags.DEFINE_string('pipeline_config_path', None,
                    'Path to a pipeline_pb2.TrainEvalPipelineConfig config '
                    'file.')
flags.DEFINE_string('trained_checkpoint_prefix', None,
                    'Path to trained checkpoint, typically of the form '
                    'path/to/model.ckpt')
flags.DEFINE_string('output_directory', None, 'Path to write outputs.')
# tf.app.flags.mark_flag_as_required('pipeline_config_path')
# tf.app.flags.mark_flag_as_required('trained_checkpoint_prefix')
# tf.app.flags.mark_flag_as_required('output_directory')

FLAGS = flags.FLAGS


def _get_outputs_from_inputs(input_tensors, model,
                             output_collection_name):
    inputs = tf.to_float(input_tensors)
    preprocessed_inputs = model.preprocess(inputs)
    outputs_dict = model.predict(preprocessed_inputs)
    output_tensors = outputs_dict['class_predictions']
    return tf.identity(output_tensors, name=output_collection_name)


def _image_tensor_input_placeholder(input_shape=None):
    if input_shape is None:
        input_shape = (None, None, None, 3)
    input_tensor = tf.placeholder(
        dtype=tf.uint8, shape=input_shape, name='inputs')
    return input_tensor, input_tensor


def _build_segmentation_graph(model, input_shape, output_collection_name):
    placeholder_tensor, input_tensors = _image_tensor_input_placeholder(
            input_shape)
    outputs = _get_outputs_from_inputs(
        input_tensors=input_tensors,
        model=model,
        output_collection_name=output_collection_name)

    slim.get_or_create_global_step()
    return outputs, placeholder_tensor


def write_graph_and_checkpoint(inference_graph_def,
                               model_path,
                               input_saver_def,
                               trained_checkpoint_prefix):
    for node in inference_graph_def.node:
        node.device = ''
    with tf.Graph().as_default():
        tf.import_graph_def(inference_graph_def, name='')
        with tf.Session() as sess:
            saver = saver_lib.Saver(saver_def=input_saver_def,
                              save_relative_paths=True)
            saver.restore(sess, trained_checkpoint_prefix)
            saver.save(sess, model_path)


def export_inference_graph(pipeline_config, trained_checkpoint_prefix,
                           output_directory, input_shape=None,
                           output_collection_name='inference_op'):

    segmentation_model = model_builder.build(pipeline_config.model,
                                             is_training=False)
    tf.gfile.MakeDirs(output_directory)
    frozen_graph_path = os.path.join(output_directory,
                                   'frozen_inference_graph.pb')
    saved_model_path = os.path.join(output_directory, 'saved_model')
    model_path = os.path.join(output_directory, 'model.ckpt')

    outputs, placeholder_tensor = _build_segmentation_graph(
        model=segmentation_model,
        input_shape=input_shape,
        output_collection_name=output_collection_name)

    with tf.Session() as sess:
        train_writer = tf.summary.FileWriter('./tmp')
        train_writer.add_graph(sess.graph)

    print("Output event success!")

    #######################################################################

    saver = tf.train.Saver()
    input_saver_def = saver.as_saver_def()

    write_graph_and_checkpoint(
        inference_graph_def=tf.get_default_graph().as_graph_def(),
        model_path=model_path,
        input_saver_def=input_saver_def,
        trained_checkpoint_prefix=trained_checkpoint_prefix)


    output_node_names = ','.join(outputs.keys())

    freeze_graph_with_def_protos(
        input_graph_def=tf.get_default_graph().as_graph_def(),
        input_saver_def=input_saver_def,
        input_checkpoint=trained_checkpoint_prefix,
        output_graph=frozen_graph_path,
        output_node_names=output_node_names,
        restore_op_name='save/restore_all',
        filename_tensor_name='save/Const:0',
        clear_devices=True,
        initializer_nodes='')


def main(_):
    pipeline_config = pipeline_pb2.PipelineConfig()
    with tf.gfile.GFile(FLAGS.pipeline_config_path, 'r') as f:
        text_format.Merge(f.read(), pipeline_config)
    if FLAGS.input_shape:
        input_shape = [
            int(dim) if dim != '-1' else None
            for dim in FLAGS.input_shape.split(',')]
    else:
        input_shape = None

    export_inference_graph(pipeline_config,
                           FLAGS.trained_checkpoint_prefix,
                           FLAGS.output_directory, input_shape)


if __name__ == '__main__':
    tf.app.run()