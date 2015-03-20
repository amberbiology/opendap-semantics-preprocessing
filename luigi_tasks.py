import luigi
import glob
import os
from tasks.parse_tasks import ParseTask


class ParseWorkflow(luigi.Task):
    doc_dir = luigi.Parameter()
    yaml_file = luigi.Parameter()

    def requires(self):
        return [ParseTask(input_path=f, yaml_file=self.yaml_file) for f in self._iterator()]

    def output(self):
        return luigi.LocalTarget('log.txt')

    def run(self):
        print 'running'

    def _iterator(self):
        for f in glob.glob(os.path.join(self.doc_dir, '*.json'))[0:10]:
            yield f


if __name__ == '__main__':
    # luigi.run(["--local-scheduler"], main_task_cls=ResponseTask)
    # luigi.run()

    # rt = ResponseTask(
    #     input_path='testdata/docs/response_0a80f182ed59a834572e2c594aacfe29.json',
    #     output_path='testdata/luigi/0a80f182ed59a834572e2c594aacfe29_cleaned.json'
    # )
    # it = IdentifyTask(
    #     upstream_task=rt,
    #     # input_path='testdata/luigi/0a80f182ed59a834572e2c594aacfe29_cleaned.json',
    #     output_path='testdata/luigi/0a80f182ed59a834572e2c594aacfe29_identify.json',
    #     yaml_file='lib/configs/identifiers.yaml'
    # )
    # pt = ParseTask(
    #     upstream_task=it,
    #     # input_path='testdata/luigi/0a80f182ed59a834572e2c594aacfe29_identify.json',
    #     output_path='testdata/luigi/0a80f182ed59a834572e2c594aacfe29_parse.json'
    # )

    # this is quite unfortunate
    w = ParseWorkflow(doc_dir='testdata/docs/', yaml_file='lib/configs/identifiers.yaml')

    luigi.build([w], local_scheduler=True)

    # for the response only: python luigi_tasks.py ResponseTask
    #       --input-path 'testdata/docs/response_0a80f182ed59a834572e2c594aacfe29.json'
    #       --output-path 'testdata/luigi/0a80f182ed59a834572e2c594aacfe29_response.json'
    #       --local-scheduler
