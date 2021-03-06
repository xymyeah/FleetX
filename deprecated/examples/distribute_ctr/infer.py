# Copyright (c) 2019 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function
import os
import time
import numpy as np
import logging
from argument import params_args
import paddle
import paddle.fluid as fluid
from network import CTR
import py_reader_generator as py_reader

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("fluid")
logger.setLevel(logging.INFO)


def run_infer(params, model_path):
    place = fluid.CPUPlace()
    train_generator = py_reader.CriteoDataset(params.sparse_feature_dim)
    file_list = [
        str(params.test_files_path) + "/%s" % x
        for x in os.listdir(params.test_files_path)
    ]
    test_reader = paddle.batch(train_generator.test(file_list),
                               batch_size=params.batch_size)
    startup_program = fluid.framework.Program()
    test_program = fluid.framework.Program()
    ctr_model = CTR()

    def set_zero(var_name):
        param = fluid.global_scope().var(var_name).get_tensor()
        param_array = np.zeros(param._get_dims()).astype("int64")
        param.set(param_array, place)

    with fluid.framework.program_guard(test_program, startup_program):
        with fluid.unique_name.guard():
            inputs = ctr_model.input_data(params)
            loss, auc_var, batch_auc_var = ctr_model.net(inputs, params)

            exe = fluid.Executor(place)
            feeder = fluid.DataFeeder(feed_list=inputs, place=place)

            fluid.io.load_persistables(
                executor=exe,
                dirname=model_path,
                main_program=fluid.default_main_program())

            auc_states_names = [
                '_generated_var_0', '_generated_var_1', '_generated_var_2',
                '_generated_var_3'
            ]
            for name in auc_states_names:
                set_zero(name)

            run_index = 0
            infer_auc = 0
            L = []
            for batch_id, data in enumerate(test_reader()):
                loss_val, auc_val = exe.run(test_program,
                                            feed=feeder.feed(data),
                                            fetch_list=[loss, auc_var])
                run_index += 1
                infer_auc = auc_val
                L.append(loss_val / params.batch_size)
                if batch_id % 100 == 0:
                    logger.info("TEST --> batch: {} loss: {} auc: {}".format(
                        batch_id, loss_val / params.batch_size, auc_val))

            infer_loss = np.mean(L)
            infer_result = {}
            infer_result['loss'] = infer_loss
            infer_result['auc'] = infer_auc
            log_path = model_path + '/infer_result.log'
            logger.info(str(infer_result))
            with open(log_path, 'w+') as f:
                f.write(str(infer_result))
            logger.info("Inference complete")
    return infer_result


if __name__ == "__main__":
    params = params_args()
    model_list = []
    for _, dir, _ in os.walk(params.model_path):
        for model in dir:
            if "epoch" in model:
                path = "/".join([params.model_path, model])
                model_list.append(path)
    for model in model_list:
        logger.info("Test model {}".format(model))
        run_infer(params, model)