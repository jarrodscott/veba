#!/usr/bin/env python
from __future__ import print_function, division
import sys, os, argparse, glob
from collections import OrderedDict, defaultdict

import pandas as pd

# Soothsayer Ecosystem
from genopype import *
from soothsayer_utils import *

pd.options.display.max_colwidth = 100
# from tqdm import tqdm
__program__ = os.path.split(sys.argv[0])[-1]
__version__ = "2022.04.12"

# .............................................................................
# Notes
# .............................................................................
# * Make batch version that takes in a manifest file
# .............................................................................
# Primordial
# .............................................................................


# Assembly
def get_index_cmd( input_filepaths, output_filepaths, output_directory, directories, opts):

    # Command
    cmd = [
        # Filtering out small contigs
        "cat",
        opts.fasta,
        "|",
        os.environ["seqkit"],
        "seq", 
        "-m {}".format(opts.minimum_contig_length),
        "-j {}".format(opts.n_jobs),
        opts.seqkit_seq_options,
        ">",
        output_filepaths[0],

        # Create SAF file
        "&&",
        os.environ["fasta_to_saf.py"],
        "-i {}".format(output_filepaths[0]),
        ">",
        output_filepaths[1],

        "&&",
        # Bowtie2 Index
        os.environ["bowtie2-build"],
        "--threads {}".format(opts.n_jobs),
        "--seed {}".format(opts.random_state),
        opts.bowtie2_index_options,
        output_filepaths[0], # Reference
        output_filepaths[0], # Index

        # Get stats for coassembly
        "&&",
        os.environ["seqkit"],
        "stats",
        "-a", 
        "-j {}".format(opts.n_jobs),
        "-T",
        "-b",
        output_filepaths[0],
        ">",
        output_filepaths[2],
    ]

    return cmd


# Bowtie2
def get_alignment_cmd(input_filepaths, output_filepaths, output_directory, directories, opts):

    # Command
    cmd = [

# MAKE THIS A FOR LOOP WITH MAX THREADS FOR EACH ONE. THE REASON FOR THIS IS THAT IF THERE IS A SMALL SAMPLE IT WILL BE DONE QUICK BUT THE LARGER SAMPLES ARE GOING TO BE STUCK WITH ONE THREAD STILL
"""
    # Clear temporary directory just in case

rm -rf %s

# Bowtie2
%s --jobs %d -a %s -C "\t" "mkdir -p %s && %s -x %s -1 {2} -2 {3} --threads 1 --seed %d --no-unal %s | %s sort --threads 1 --reference %s -T %s > %s && %s index -@ 1 %s"

"""%( 
    os.path.join(directories["tmp"], "*"),

    # Parallel
    os.environ["parallel"],
    opts.n_jobs,
    input_filepaths[0],

    # Make directory
    os.path.join(output_directory, "{1}"),

    # Bowtie2
    os.environ["bowtie2"],
    input_filepaths[1],
    opts.random_state,
    opts.bowtie2_options,

    # Samtools sort
    os.environ["samtools"],
    input_filepaths[0],
    os.path.join(directories["tmp"], "samtools_sort_{1}"),
    os.path.join(output_directory, "{1}", "mapped.sorted.bam"),

    # Samtools index
    os.environ["samtools"],
    os.path.join(output_directory, "{1}", "mapped.sorted.bam"),

    ),


    ]

    return cmd


# featureCounts
def get_featurecounts_cmd(input_filepaths, output_filepaths, output_directory, directories, opts):

    # Command

    # ORF-Level Counts
    cmd = [
    "mkdir -p {}".format(os.path.join(directories["tmp"], "featurecounts")),
    "&&",
    "(",
        os.environ["featureCounts"],
        # "-G {}".format(input_filepaths[0]),
        "-a {}".format(input_filepaths[0]),
        "-o {}".format(os.path.join(output_directory, "featurecounts.tsv")),
        "-F SAF",
        "--tmpDir {}".format(os.path.join(directories["tmp"], "featurecounts")),
        "-T {}".format(opts.n_jobs),
        opts.featurecounts_options,
        *input_filepaths[1:],
    ")",
        "&&",
    "gzip -f {}".format(os.path.join(output_directory, "featurecounts.tsv")),
        ]
    return cmd



# Symlink
def get_symlink_cmd(input_filepaths, output_filepaths, output_directory, directories, opts):
    # Command
    cmd = ["("]
    for filepath in input_filepaths:
        # cmd.append("ln -f -s {} {}".format(os.path.realpath(filepath), os.path.realpath(output_directory)))
        cmd.append("ln -f -s {} {}".format(os.path.realpath(filepath), output_directory))
        cmd.append("&&")
    cmd[-1] = ")"
    return cmd

# ============
# Run Pipeline
# ============
# Set environment variables
def add_executables_to_environment(opts):
    """
    Adapted from Soothsayer: https://github.com/jolespin/soothsayer
    """
    accessory_scripts = {
                "fasta_to_saf.py"
                }

    required_executables={
                "bowtie2-build",
                "bowtie2",
                "samtools",
                "featureCounts",
                "seqkit",
                "parallel",
     } | accessory_scripts

    if opts.path_config == "CONDA_PREFIX":
        executables = dict()
        for name in required_executables:
            executables[name] = os.path.join(os.environ["CONDA_PREFIX"], "bin", name)
    else:
        if opts.path_config is None:
            opts.path_config = os.path.join(opts.script_directory, "veba_config.tsv")
        opts.path_config = format_path(opts.path_config)
        assert os.path.exists(opts.path_config), "config file does not exist.  Have you created one in the following directory?\n{}\nIf not, either create one, check this filepath:{}, or give the path to a proper config file using --path_config".format(opts.script_directory, opts.path_config)
        assert os.stat(opts.path_config).st_size > 1, "config file seems to be empty.  Please add 'name' and 'executable' columns for the following program names: {}".format(required_executables)
        df_config = pd.read_csv(opts.path_config, sep="\t")
        assert {"name", "executable"} <= set(df_config.columns), "config must have `name` and `executable` columns.  Please adjust file: {}".format(opts.path_config)
        df_config = df_config.loc[:,["name", "executable"]].dropna(how="any", axis=0).applymap(str)
        # Get executable paths
        executables = OrderedDict(zip(df_config["name"], df_config["executable"]))
        assert required_executables <= set(list(executables.keys())), "config must have the required executables for this run.  Please adjust file: {}\nIn particular, add info for the following: {}".format(opts.path_config, required_executables - set(list(executables.keys())))

    # Display
    for name in sorted(accessory_scripts):
        executables[name] = "python " + os.path.join(opts.script_directory, "scripts", name)
    print(format_header( "Adding executables to path from the following source: {}".format(opts.path_config), "-"), file=sys.stdout)
    for name, executable in executables.items():
        if name in required_executables:
            print(name, executable, sep = " --> ", file=sys.stdout)
            os.environ[name] = executable.strip()
    print("", file=sys.stdout)

# Pipeline
def create_pipeline(opts, directories, f_cmds):

    # .................................................................
    # Primordial
    # .................................................................
    # Commands file
    pipeline = ExecutablePipeline(name=__program__, description="Coassembly", f_cmds=f_cmds, checkpoint_directory=directories["checkpoints"], log_directory=directories["log"])

    # ==========
    # Assembly
    # ==========
    
    step = 1

    # Info
    program = "index"
    program_label = "{}__{}".format(step, program)
    description = "Preprocess fasta file and build Bowtie2 index"
    
    # Add to directories
    output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))


    # i/o
    input_filepaths = [opts.fasta]
    output_filenames = ["coassembly.fasta", "coassembly.fasta.saf", "seqkit_stats.tsv", "coassembly.fasta.*.bt2"]


    output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))

    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = get_index_cmd(**params)
    pipeline.add_step(
                id=program_label,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
                log_prefix=program_label,

    )

    # ==========
    # Alignment
    # ==========
    
    step = 2

    # Info
    program = "alignment"
    program_label = "{}__{}".format(step, program)
    description = "Aligning reads to coassembly"

    # Add to directories
    output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))


    # i/o
    input_filepaths = [
            opts.reads,
            os.path.join(directories[("intermediate", "1__index")], "coassembly.fasta"),
        ]



    output_filenames = ["*/mapped.sorted.bam"]
    output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))


    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = get_alignment_cmd(**params)
    pipeline.add_step(
                id=program_label,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
                log_prefix=program_label,

    )



    # ==========
    # featureCounts
    # ==========
    step = 3 

    # Info
    program = "featurecounts"
    program_label = "{}__{}".format(step, program)
    description = "Counting reads"

    # Add to directories
    output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))

    # i/o

    input_filepaths = [ 
        os.path.join(directories[("intermediate", "1__index")], "coassembly.fasta.saf"),
        os.path.join(directories[("intermediate", "2__alignment")], "*", "mapped.sorted.bam"),
    ]

    output_filenames = ["featurecounts.tsv.gz"]
    output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))

    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = get_featurecounts_cmd(**params)
    pipeline.add_step(
                id=program_label,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
                log_prefix=program_label,

    )

   


    # =============
    # Symlink
    # =============
    step = 4

    # Info
    program = "symlink"
    program_label = "{}__{}".format(step, program)
    description = "Symlinking relevant output files"

    # Add to directories
    output_directory = directories["output"]

    # i/o

    input_filepaths = [
            os.path.join(directories[("intermediate", "1__index")], "coassembly.fasta"),
            os.path.join(directories[("intermediate", "1__index")], "coassembly.fasta.saf"),
            os.path.join(directories[("intermediate", "1__index")], "seqkit_stats.tsv"),
            os.path.join(directories[("intermediate", "2__alignment")], "*"),
            os.path.join(directories[("intermediate", "3__featurecounts")], "featurecounts.tsv.gz"),
        ]

    output_filenames =  map(lambda fp: fp.split("/")[-1], input_filepaths)
    output_filepaths = list(map(lambda fn:os.path.join(directories["output"], fn), output_filenames))

    params = {
    "input_filepaths":input_filepaths,
    "output_filepaths":output_filepaths,
    "output_directory":output_directory,
    "opts":opts,
    "directories":directories,
    }

    cmd = get_symlink_cmd(**params)
    pipeline.add_step(
            id=program_label,
            description = description,
            step=step,
            cmd=cmd,
            input_filepaths = input_filepaths,
            output_filepaths = output_filepaths,
            validate_inputs=True,
            validate_outputs=True,
            log_prefix=program_label,

    )

    return pipeline

# Configure parameters
def configure_parameters(opts, directories):
    # os.environ[]

        # assert not bool(opts.unpaired_reads), "Cannot have --unpaired_reads if --forward_reads.  Note, this behavior may be changed in the future but it's an adaptation of interleaved reads."
    df = pd.read_csv(opts.reads, sep="\t", header=None)
    n, m = df.shape
    assert m == 3, "--reads must be a 3 column table seperated by tabs and no header. Currently there are {} columns".format(m)
    # Set environment variables
    add_executables_to_environment(opts=opts)

def main(args=None):
    # Path info
    script_directory  =  os.path.dirname(os.path.abspath( __file__ ))
    script_filename = __program__
    # Path info
    description = """
    Running: {} v{} via Python v{} | {}""".format(__program__, __version__, sys.version.split(" ")[0], sys.executable)
    usage = "{} -f <coassembly.fasta> -r <reads.tsv> -o <output_directory>".format(__program__)
    epilog = "Copyright 2021 Josh L. Espinoza (jespinoz@jcvi.org)"

    # Parser
    parser = argparse.ArgumentParser(description=description, usage=usage, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)
    # Pipeline
    parser_io = parser.add_argument_group('Required I/O arguments')
    parser_io.add_argument("-f","--fasta", type=str, required=True, help = "path/to/coassembly.fasta [Required]")
    parser_io.add_argument("-r","--reads", type=str, required = True, help = "path/to/reads_table.tsv with the following format: [id_sample]<tab>[path/to/r1.fastq.gz]<tab>[path/to/r2.fastq.gz], No header")
    parser_io.add_argument("-o","--output_directory", type=str, default="veba_output/assembly/coassembly", help = "path/to/project_directory [Default: veba_output/assembly/coassembly]")

    # Utility
    parser_utility = parser.add_argument_group('Utility arguments')
    parser_utility.add_argument("--path_config", type=str,  default="CONDA_PREFIX", help="path/to/config.tsv [Default: CONDA_PREFIX]")  #site-packges in future
    parser_utility.add_argument("-p", "--n_jobs", type=int, default=1, help = "Number of threads [Default: 1]")
    parser_utility.add_argument("--random_state", type=int, default=0, help = "Random state [Default: 0]")
    parser_utility.add_argument("--restart_from_checkpoint", type=str, default=None, help = "Restart from a particular checkpoint [Default: None]")
    parser_utility.add_argument("-v", "--version", action='version', version="{} v{}".format(__program__, __version__))
    parser_utility.add_argument("--tmpdir", type=str, help="Set temporary directory")  #site-packges in future

    # Aligner
    parser_seqkit = parser.add_argument_group('SeqKit seq arguments')
    parser_seqkit.add_argument("-m", "--minimum_contig_length", type=int, default=1500, help="seqkit seq | Minimum contig length [Default: 1500]")
    parser_seqkit.add_argument("--seqkit_seq_options", type=str, default="", help="seqkit seq | More options (e.g. --arg 1 ) [Default: '']")


    # Aligner
    parser_aligner = parser.add_argument_group('Bowtie2 arguments')
    parser_aligner.add_argument("--bowtie2_index_options", type=str, default="", help="bowtie2-build | More options (e.g. --arg 1 ) [Default: '']")
    parser_aligner.add_argument("--bowtie2_options", type=str, default="", help="bowtie2 | More options (e.g. --arg 1 ) [Default: '']")

    # featureCounts
    parser_featurecounts = parser.add_argument_group('featureCounts arguments')
    parser_featurecounts.add_argument("--featurecounts_options", type=str, default="", help="featureCounts | More options (e.g. --arg 1 ) [Default: ''] | http://bioinf.wehi.edu.au/featureCounts/")


    # Options
    opts = parser.parse_args()
    opts.script_directory  = script_directory
    opts.script_filename = script_filename

    # Directories
    directories = dict()
    directories["project"] = create_directory(opts.output_directory)
    directories["output"] = create_directory(os.path.join(directories["project"], "output"))
    directories["log"] = create_directory(os.path.join(directories["project"], "log"))
    if not opts.tmpdir:
        opts.tmpdir = os.path.join(directories["project"], "tmp")
    directories["tmp"] = create_directory(opts.tmpdir)
    directories["checkpoints"] = create_directory(os.path.join(directories["project"], "checkpoints"))
    directories["intermediate"] = create_directory(os.path.join(directories["project"], "intermediate"))
    os.environ["TMPDIR"] = directories["tmp"]

    # Info
    print(format_header(__program__, "="), file=sys.stdout)
    print(format_header("Configuration:", "-"), file=sys.stdout)
    print("Python version:", sys.version.replace("\n"," "), file=sys.stdout)
    print("Python path:", sys.executable, file=sys.stdout) #sys.path[2]
    print("Script version:", __version__, file=sys.stdout)
    print("Moment:", get_timestamp(), file=sys.stdout)
    print("Directory:", os.getcwd(), file=sys.stdout)
    print("Commands:", list(filter(bool,sys.argv)),  sep="\n", file=sys.stdout)
    configure_parameters(opts, directories)
    sys.stdout.flush()

    # Run pipeline
    with open(os.path.join(directories["project"], "commands.sh"), "w") as f_cmds:
        pipeline = create_pipeline(
                     opts=opts,
                     directories=directories,
                     f_cmds=f_cmds,
        )
        pipeline.compile()
        pipeline.execute(restart_from_checkpoint=opts.restart_from_checkpoint)

if __name__ == "__main__":
    main()
