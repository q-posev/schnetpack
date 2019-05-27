#!/usr/bin/env python
import argparse
import logging
import os
import torch

import schnetpack as spk

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))


class SpecialOption(argparse.Action):
    """
    Special argparse option. If option is not called, False is stored.
    If the option is called without argument, the value in const is provided as default.
    If the option is called with an argumeny, this argument is used as the value.
    """

    def __init__(
        self,
        option_strings,
        const,
        dest,
        type=type,
        default=False,
        required=False,
        help=None,
    ):
        super(SpecialOption, self).__init__(
            option_strings=option_strings,
            const=const,
            dest=dest,
            type=type,
            nargs="?",
            default=default,
            required=required,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)


def get_parser():
    """ Setup parser for command line arguments """
    main_parser = argparse.ArgumentParser()

    # General commands
    main_parser.add_argument("molecule_path", help="Initial geometry")
    main_parser.add_argument("model_path", help="Path of trained model")
    main_parser.add_argument("simulation_dir", help="Path to store MD data")
    main_parser.add_argument(
        "--device", help="Choose between 'cpu' and 'cuda'", default="cpu"
    )

    # Optimization:
    main_parser.add_argument(
        "--optimize",
        const=1000,
        action=SpecialOption,
        type=int,
        help="Optimize geometry. A default of 1000 steps is used.",
    )

    # Normal modes
    main_parser.add_argument(
        "--normal_modes", help="Compute normal modes", action="store_true"
    )

    # Molecular dynamics options
    main_parser.add_argument(
        "--equilibrate",
        const=10000,
        action=SpecialOption,
        type=int,
        help="Equilibrate molecule for molecular dynamics. A default of 10000 steps is used.",
    )
    main_parser.add_argument(
        "--production",
        const=10000,
        action=SpecialOption,
        type=int,
        help="Production molecular dynamics (default: %(default)s)",
    )
    main_parser.add_argument(
        "--interval",
        type=int,
        default=100,
        help="Log trajectory every N steps (default: %(default)s)",
    )
    main_parser.add_argument(
        "--time_step",
        type=float,
        default=0.5,
        help="Timestep in fs (default: %(default)s)",
    )

    # Temperature and bath options
    main_parser.add_argument(
        "--temp_init",
        type=float,
        default=300.0,
        help="Initial temperature used for molecular"
        " dynamics in K. (default: %(default)s)",
    )
    main_parser.add_argument(
        "--temp_bath",
        type=float,
        default=None,
        help="Temperature of bath. If None is given, NVE"
        " dynamics are run. (default: %(default)s)",
    )

    main_parser.add_argument(
        "--single_point",
        action="store_true",
        help="Perform a single point prediction on the "
        "current geometry (energies and forces).",
    )
    main_parser.add_argument(
        "--energy",
        type=str,
        help="Property name to the energy property in the dataset which has been "
        "used for training the model",
        default="energy",
    )
    main_parser.add_argument(
        "--forces",
        type=str,
        help="Property name to the forces property in the dataset which has been "
        "used for training the model",
        default="forces",
    )

    return main_parser


if __name__ == "__main__":

    parser = get_parser()
    args = parser.parse_args()
    argparse_dict = vars(args)
    jsonpath = os.path.join(args.simulation_dir, "args.json")

    # Set up directory
    if not os.path.exists(args.simulation_dir):
        os.makedirs(args.simulation_dir)

    # Store command line args
    spk.spk_utils.to_json(jsonpath, argparse_dict)

    # Load the model
    ml_model = torch.load(args.model_path)
    logging.info("Loaded model.")

    logging.info(
        "The model you built has: {:d} parameters".format(
            spk.spk_utils.compute_params(ml_model)
        )
    )

    # Initialize the ML ase interface
    ml_calculator = spk.interfaces.AseInterface(
        args.molecule_path,
        ml_model,
        args.simulation_dir,
        args.device,
        args.energy,
        args.forces,
    )
    logging.info("Initialized ase driver")

    # Perform the requested simulations

    if args.single_point:
        logging.info("Single point prediction...")
        ml_calculator.calculate_single_point()

    if args.optimize:
        logging.info("Optimizing geometry...")
        ml_calculator.optimize(steps=args.optimize)

    if args.normal_modes:
        if not args.optimize:
            logging.warning(
                "Computing normal modes without optimizing the geometry makes me a sad schnetpack..."
            )
        logging.info("Computing normal modes...")
        ml_calculator.compute_normal_modes()

    if args.equilibrate:
        logging.info("Equilibrating the system...")
        if args.temp_bath is None:
            raise ValueError("Please supply bath temperature for equilibration")
        ml_calculator.init_md(
            "equilibration",
            time_step=args.time_step,
            interval=args.interval,
            temp_bath=args.temp_bath,
            temp_init=args.temp_init,
        )
        ml_calculator.run_md(args.equilibrate)

    if args.production:
        logging.info("Running production dynamics...")
        ml_calculator.init_md(
            "production",
            time_step=args.time_step,
            interval=args.interval,
            temp_bath=args.temp_bath,
            temp_init=args.temp_init,
        )
        ml_calculator.run_md(args.production)
