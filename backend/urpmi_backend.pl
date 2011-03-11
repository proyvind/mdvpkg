#!/usr/bin/perl

use warnings;
use strict;

use URPM;
use urpm;
use urpm::media;
use urpm::args;
use urpm::select;

$| = 1;

my $urpm = urpm->new_parse_cmdline;
# URPM db, initially not opened
my $db;
urpm::media::configure($urpm);

while (<>) {
    chomp($_);
    $_ or next;
    my ($cmd, @args) = split /\s+/, $_;
    # TODO Check if it's defined:
    $main::{"on_command__$cmd"}->(@args);
}

sub to_bool {
    return $_[0] ? 'True' : 'False';
}

sub py_package_str {
    my ($pkg, $installed) = @_;
    my $py_str = '(';
    foreach my $part ($pkg->fullname()) { 
	$py_str .= "'$part',";
    }
    $py_str .= to_bool($installed) . ")\n";
    return $py_str;
}

sub open_urpm_db {
    if (not $db) {
	# TODO die() if not possible to open:
	$db = URPM::DB::open();
	$urpm->compute_installed_flags($db);
    }
    return $db;
}

##
# traverse_pacakges - traverse all installed and installable packages
#
# $urpm		urpm object
# $db		URPM::DB object
# $callback	$callback->($pkg, $installed) for each package
#
sub traverse_packages {
    my ($urpm, $db, $callback) = @_;

    # Traverse installed packages ...
    $db->traverse(sub { $callback->($_[0], 1) });

    # Traverse installable packages ...
    foreach my $pkg (@{$urpm->{depslist}}) {
        if ($pkg->flag_upgrade) {
	    $callback->($pkg, 0);
	}
    }
}

#
# Command Handlers
#

sub on_command__list_medias {
    foreach (@{$urpm->{media}}) {
	my ($name, $update, $ignore) 
	    = ($_->{name}, $_->{update}, $_->{ignore});
	printf("('%s', %s, %s)\n", $name, to_bool($update), to_bool($ignore))
    }
    print "\n";
}

sub on_command__list_packages {
    my $db = open_urpm_db();

    traverse_packages($urpm, $db, sub {
	                              print py_package_str(@_)
		                  });
    print "\n";
}

sub on_command__list_groups {
    my $db = open_urpm_db();
    my %groups = ();

    traverse_packages(
	$urpm, 
	$db,
	sub {
	    my ($pkg, $installed) = @_;
	    my $group = $pkg->group();
	    exists $groups{$group} or $groups{$group} = 0;
	    ++$groups{$group};
	}
	);

    foreach my $group (keys %groups) {
	my $count = $groups{$group};
	print "('$group', $count)\n";
    }

    print "\n";
}

sub on_command__package_details {
    my ($name) = @_;
    my $db = open_urpm_db();

    foreach my $media (@{$urpm->{media}}) {
        next if $media->{ignore};
        my $media_name = $media->{name};
        my $start = $media->{start};
        my $end = $media->{end};

        foreach my $pkg (@{$urpm->{depslist}}[$start..$end]) {
            if ($pkg->name eq $name) {
                my $installtime = '';
                if ($pkg->flag_installed) {
                    $installtime = `rpm -q $name --qf '%{installtime}'`
                }
                printf("{'name': '%s', 'version': '%s', 'group': '%s', "
                           . "'summary': '%s', 'media': '%s', "
                           . "'installtime': '%s'}\n",
                       $pkg->name,
                       $pkg->version,
                       $pkg->group, 
                       $pkg->summary, 
                       $media_name,
                       $installtime);
            }
        }
    }

    print "\n";
}
