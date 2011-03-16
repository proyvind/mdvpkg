#!/usr/bin/perl

##
## Copyright (C) 2010-2011 Mandriva S.A <http://www.mandriva.com>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
##
## Author(s): J. Victor Martins <jvdm@mandriva.com>
##


## TODO ##
#
# 1. Use asynchronous responses (requires a better ipc protocol),
#    allowing caller to use co-routines.
#
# 2. Include error handling in ipc protocol.
#


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

    my %args = ();
    foreach (@args) {
        my ($name, $value) = split /=/;
        $args{$name} = $value;
    }

    # TODO Check if it's defined:
    $main::{"on_command__$cmd"}->(%args);
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
    my (%args) = @_;
    my $db = open_urpm_db();
    my $name = $args{name};

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

sub on_command__search_files {
    my (%args) = @_;
    
    # For each medium, we browse the xml info file, while looking for
    # files which matched with the search term given in argument. We
    # store results in a hash ...

    my %results;

    foreach my $medium (urpm::media::non_ignored_media($urpm)) {
	my $xml_info_file = urpm::media::any_xml_info($urpm,
						      $medium,
						      qw( files summary ),
						      undef,
						      undef);
	$xml_info_file or next;

	require urpm::xml_info;
	require urpm::xml_info_pkg;

	my $F = urpm::xml_info::open_lzma($xml_info_file);
	my $fn;
	local $_;
	my @files = ();
	while (<$F>) {
	    chomp;
	    if (/<files/) {
		($fn) = /fn="(.*)"/;
	    } 
	    elsif (/^$args{pattern}$/ or ($args{fuzzy} and /$args{pattern}/)) {
		my $xml_pkg = urpm::xml_info_pkg->new({ fn => $fn });
		if (not exists $results{$fn}) {
		    $results{$fn} = { pkg => $xml_pkg,
				      files => [] };
		}
		push @{ $results{$fn}{files} }, $_;
	    }
	}
    }

    foreach my $fn (keys %results) {
	my $xml_pkg = $results{$fn}{pkg};
	printf("{'name': '%s', 'version': '%s', 'release': '%s', " 
	       . "'arch': '%s', 'files': [",
	       $xml_pkg->name,
	       $xml_pkg->version,
	       $xml_pkg->release,
	       $xml_pkg->arch);
	printf("'%s', ", $_) for (@{ $results{$fn}{files} });
	print "]}\n";
    }

    print "\n";
}
