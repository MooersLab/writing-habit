# Tutorials

Two walkthroughs run the same writing week from plan to dashboard. They reach
the same database, produce the same reports, and differ only in how you drive
the tools.

| Walkthrough | Drive it with | Read this one when |
|-------------|---------------|--------------------|
| [One writing week from plan to dashboard](tutorial.md) | typed commands | you live in a terminal, you want to script the loop, or you have not installed the graphical extra |
| [The same writing week, by point and click](tutorial-gui.md) | the `writing-habit-gui` window | you are learning the tools, you want the weekly table edited in a grid, or you prefer to see each report as it appears |

Neither is the primary one. The interface generates its forms from the same
`argparse` parsers the command line uses and calls the same functions, so a step
you learn in one transfers directly to the other. Every form in the window shows
the shell command it will run, which is the fastest way to move from the second
walkthrough to the first.

```{toctree}
:maxdepth: 1

tutorial
tutorial-gui
```
