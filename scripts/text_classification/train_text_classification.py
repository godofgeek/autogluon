from autogluon import text_classification as task

import logging
logging.basicConfig(level=logging.INFO)

dataset = task.Dataset(name='SST')

time_limits = 3*60 # 3mins
num_training_epochs = 10
results = task.fit(dataset,
                   time_limits=time_limits,
                   num_training_epochs=num_training_epochs,
                   accumulate=1,
                   batch_size=16,
                   bert_dataset='book_corpus_wiki_en_uncased',
                   bert_model='bert_12_768_12',
                   dev_batch_size=8, epochs=4, gpu=True,
                   log_interval=500, lr=2e-05, max_len=128,
                   model_parameters=None, optimizer='bertadam',
                   output_dir='./output_dir', pretrained_bert_parameters=None,
                   seed=2, task_name='SST', warmup_ratio=0.1, epsilon=1e-6,
                   dtype='float32', only_inference=False)

print('Top-1 val acc: %.3f' % results.metric)

# test_acc = task.evaluate(dataset)
# print('Top-1 test acc: %.3f' % test_acc)
#
# sentence = 'I feel this is awesome!'
# ind, prob = task.predict(sentence)
# print('The input sentence is classified as [%s], with probability %.2f.' %
#       (dataset.train.synsets[ind.asscalar()], prob.asscalar()))
#
# print('The best configuration is:')
# print(results.config)